############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/15
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Lazy, memory-bounded, editable access to a multi-material ENDF file.

:class:`EndfFile` indexes a tape on construction and reads and parses
individual sections from disk only when they are accessed, keeping the
results in bounded caches (see :mod:`endf_parserpy.tape.cache`). A
single section is parsed by wrapping its records in a minimal
single-material tape and handing that to an ordinary parser, so the
parsing engine is used unchanged.

Each material is represented by a :class:`_MaterialSlot` that carries an
edit overlay. Sections can be replaced, added or deleted and materials
can be deleted, appended or reordered; :meth:`EndfFile.save` writes the
edited tape back out. Untouched sections are written verbatim from disk,
so an unedited round trip is byte-exact.
"""

import os
import threading
from collections.abc import Mapping

from ..endf_parser_factory import EndfParserFactory
from .address import (
    EndfMaterialPath,
    parse_section_path,
    section_has,
    walk_section,
)
from .cache import _RawCache, _SectionCache, _Section
from .errors import AmbiguousMaterialError, SectionParseError, StaleSourceError
from .index import TapeIndex
from .material import MaterialView, _MaterialSlot
from .operations import write_tape
from .splitter import _control_numbers


_VALID_MODES = ("index", "load_raw", "parse_all")
_VALID_ON_ERROR = ("raise", "mark")
_BACKEND_OF = {"EndfParserCpp": "cpp", "EndfParserPy": "python"}

# sentinel distinguishing "no value given" from an explicit value of None
_UNSET = object()


def _control_line(mat, mf, mt):
    """Build a control-only ENDF record (used for FEND/MEND/TEND)."""
    return " " * 66 + f"{mat:>4}{mf:>2}{mt:>3}"


def _value_match(field, value, tol):
    if tol and isinstance(field, (int, float)) and isinstance(value, (int, float)):
        return abs(field - value) <= tol
    return field == value


def _strip_send(lines):
    """Drop a trailing SEND record from a section's raw lines.

    The structural index spans a section through its SEND record, but
    the writer re-emits the SEND itself, so a raw section handed to the
    writer must not already carry one.
    """
    if lines and _control_numbers(lines[-1])[2] == 0:
        return lines[:-1]
    return list(lines)


class _CurrentMaterials:
    """Adapter exposing the current slot list with a TapeIndex-like API.

    Lets :meth:`EndfMaterialPath.resolve_material` resolve against the
    *current* (possibly edited) material order rather than the
    on-disk index.
    """

    def __init__(self, slots):
        self._slots = slots

    def __len__(self):
        return len(self._slots)

    def by_mat(self, mat):
        return [i for i, s in enumerate(self._slots) if s.mat == mat]

    def by_za(self, za):
        return [i for i, s in enumerate(self._slots) if s.za == za]


class FailedSection:
    """Placeholder for a section that could not be parsed.

    Returned by section access when the :class:`EndfFile` was opened
    with ``on_error="mark"`` and the section failed to parse.

    Attributes
    ----------
    exception : Exception
        The exception raised while parsing the section.
    raw_lines : list[str]
        The raw text of the section.
    position : int
        Position of the material the section belongs to.
    mf, mt : int
        The MF/MT numbers of the section.
    """

    def __init__(self, exception, raw_lines, position, mf, mt):
        self.exception = exception
        self.raw_lines = list(raw_lines)
        self.position = position
        self.mf = mf
        self.mt = mt

    def __repr__(self):
        return (
            f"FailedSection(position={self.position}, MF={self.mf}, "
            f"MT={self.mt}, exception={self.exception!r})"
        )


class EndfFile:
    """Lazy, memory-bounded, editable view of a multi-material ENDF file.

    The file is indexed on construction (see :class:`TapeIndex`).
    Section data is read from disk and parsed only on access and is then
    held in bounded caches. Materials are addressed by zero-based
    position::

        with EndfFile("tape.endf") as endf_file:
            material = endf_file[0]         # a MaterialView
            section = material[3, 2]        # parsed MF=3/MT=2 section
            material[3, 2] = section        # edit it back in
            endf_file.save("edited.endf")

    Parameters
    ----------
    filename : str or os.PathLike
        Path to the ENDF file.
    parser : EndfParserBase, optional
        Engine used to parse and write sections. Defaults to
        ``EndfParserFactory.create(select="fastest")``.
    mode : {"index", "load_raw", "parse_all"}
        ``"index"`` (default) only builds the index. ``"load_raw"`` also
        pre-reads section text into the raw cache; ``"parse_all"`` also
        parses every section. The cache budgets still apply, so these
        modes pre-warm the caches rather than guarantee residency.
    parsed_cache_bytes, raw_cache_bytes : int
        Budgets, in raw-text-equivalent bytes, for the parsed-section
        and raw-text caches.
    on_error : {"raise", "mark"}
        Whether a section that fails to parse raises
        :class:`SectionParseError` or is returned as a
        :class:`FailedSection`.
    verify_source : bool
        If true, the file's size and mtime are checked against the
        index before every disk read; a change raises
        :class:`StaleSourceError`.
    """

    def __init__(
        self,
        filename,
        *,
        parser=None,
        mode="index",
        parsed_cache_bytes=64 << 20,
        raw_cache_bytes=64 << 20,
        on_error="mark",
        verify_source=False,
    ):
        if mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"on_error must be one of {_VALID_ON_ERROR}, got {on_error!r}"
            )
        self._path = os.fspath(filename)
        self._parser = parser or EndfParserFactory.create(select="fastest")
        self._backend = _BACKEND_OF.get(type(self._parser).__name__, "fastest")
        self._on_error = on_error
        self._verify_source = verify_source
        self._index = TapeIndex.from_file(self._path)
        self._materials = [
            _MaterialSlot(e.position, e.mat, e.za, e.awr) for e in self._index
        ]
        self._raw_cache = _RawCache(raw_cache_bytes)
        self._section_cache = _SectionCache(parsed_cache_bytes)
        self._material_views = {}
        self._secondary_indexes = {}
        self._lock = threading.RLock()
        if mode == "load_raw":
            self._preload(parse=False)
        elif mode == "parse_all":
            self._preload(parse=True)

    def _preload(self, parse):
        for entry in self._index:
            for mf, mt in list(entry.sections):
                if parse:
                    self._get_section(entry.position, mf, mt)
                else:
                    self._get_raw(entry.position, mf, mt, entry.sections[(mf, mt)])

    # -- mapping protocol over materials -------------------------------

    def __len__(self):
        return len(self._materials)

    def __getitem__(self, position):
        if not isinstance(position, int):
            raise TypeError(
                "EndfFile is indexed by integer material position; use "
                "by_mat() or by_za() for other lookups"
            )
        slot = self._materials[position]
        view = self._material_views.get(slot)
        if view is None:
            view = MaterialView(self, slot)
            self._material_views[slot] = view
        return view

    def __iter__(self):
        for position in range(len(self._materials)):
            yield self[position]

    def __delitem__(self, position):
        """Delete the material at ``position`` from the tape."""
        with self._lock:
            del self._materials[position]

    def materials(self):
        """Return all materials as a list of :class:`MaterialView` objects."""
        return list(self)

    def _position_of(self, slot):
        try:
            return self._materials.index(slot)
        except ValueError:
            raise RuntimeError("this material has been deleted from the tape") from None

    # -- editing -------------------------------------------------------

    def append_material(self, material, *, mat, za=None, awr=None):
        """Append a new material to the tape.

        Parameters
        ----------
        material : Mapping
            A nested ``{MF: {MT: section}}`` mapping, as returned by an
            ordinary ``parsefile``. The ``MF=0`` tape-head entry, if
            present, is ignored.
        mat : int
            ENDF MAT number of the new material.
        za, awr : optional
            Identifiers, used by :meth:`by_za` and the index.

        Returns
        -------
        MaterialView
            A view of the appended material.
        """
        slot = _MaterialSlot(original_position=None, mat=mat, za=za, awr=awr)
        for mf, mtdic in material.items():
            if mf == 0:
                continue
            for mt, section in mtdic.items():
                slot.overlay[(int(mf), int(mt))] = section
        with self._lock:
            self._materials.append(slot)
        return self[len(self._materials) - 1]

    def reorder(self, order):
        """Reorder the materials of the tape.

        ``order`` is a permutation of ``range(len(self))``: the material
        currently at ``order[i]`` moves to position ``i``.
        """
        order = list(order)
        if sorted(order) != list(range(len(self._materials))):
            raise ValueError("order must be a permutation of range(len(self))")
        with self._lock:
            self._materials = [self._materials[i] for i in order]

    # -- secondary lookups ---------------------------------------------

    def by_mat(self, mat, *, occurrence=None):
        """Return the material with the given MAT number.

        ``occurrence`` (zero-based) selects among several materials that
        share a MAT number, as on a PENDF tape. Without it, a MAT number
        that is not unique raises :class:`AmbiguousMaterialError`.
        """
        positions = [i for i, s in enumerate(self._materials) if s.mat == mat]
        if not positions:
            raise KeyError(f"no material with MAT={mat}")
        if occurrence is not None:
            return self[positions[occurrence]]
        if len(positions) > 1:
            raise AmbiguousMaterialError(
                f"MAT={mat} matches {len(positions)} materials at positions "
                f"{positions}; pass occurrence=0..{len(positions) - 1}"
            )
        return self[positions[0]]

    def by_za(self, za):
        """Return a list of materials with the given ZA identifier."""
        return [self[i] for i, s in enumerate(self._materials) if s.za == za]

    def find(self, *, mat=None, za=None):
        """Return a list of materials matching every given criterion.

        This is the structural lookup. For lookups by a parsed section
        field, see :meth:`query`.
        """
        result = []
        for i, slot in enumerate(self._materials):
            if mat is not None and slot.mat != mat:
                continue
            if za is not None and slot.za != za:
                continue
            result.append(self[i])
        return result

    # -- path-based queries --------------------------------------------

    def get(self, path):
        """Return the value addressed by an :class:`EndfMaterialPath`.

        ``path`` is an :class:`EndfMaterialPath` or a string of the form
        ``material/MF/MT[/field...]``. If the section cannot be parsed a
        :class:`SectionParseError` is raised regardless of ``on_error``.
        """
        mp = path if isinstance(path, EndfMaterialPath) else EndfMaterialPath(path)
        if mp.mf is None or mp.mt is None:
            raise ValueError(f"{mp!r} must address at least a section (material/MF/MT)")
        position = mp.resolve_material(_CurrentMaterials(self._materials))
        section = self._get_slot_section(self._materials[position], mp.mf, mp.mt)
        if isinstance(section, FailedSection):
            raise SectionParseError(
                f"cannot resolve {mp!r}: MF={mp.mf}/MT={mp.mt} of the "
                f"material at position {position} failed to parse"
            ) from section.exception
        return walk_section(section, mp.subpath)

    def build_index(self, section_path, *, name=None):
        """Build a secondary index over a section field.

        Parses the ``MF/MT`` section of every material that has it,
        reads the value at the field path and returns a dict
        ``{value: [positions]}``. This parses one section per material,
        so the cost grows with the number of materials. With ``name``
        the result is also stored and reachable via
        :attr:`secondary_indexes`.
        """
        mf, mt, subpath = parse_section_path(section_path)
        mapping = {}
        for position, slot in enumerate(self._materials):
            if (mf, mt) not in self._slot_section_keys_set(slot):
                continue
            section = self._get_slot_section(slot, mf, mt)
            if isinstance(section, FailedSection):
                if self._on_error == "raise":
                    raise SectionParseError(
                        f"MF={mf}/MT={mt} of the material at position "
                        f"{position} failed to parse"
                    ) from section.exception
                continue
            if not section_has(section, subpath):
                continue
            value = walk_section(section, subpath)
            try:
                mapping.setdefault(value, []).append(position)
            except TypeError:
                raise ValueError(
                    f"section path {section_path!r} resolves to a "
                    "non-hashable value; build_index needs a scalar field"
                ) from None
        if name is not None:
            self._secondary_indexes[name] = mapping
        return mapping

    def query(self, section_path, value=_UNSET, *, predicate=None, tol=0.0):
        """Return the materials whose section field matches.

        Pass exactly one of ``value`` (equality, within ``tol`` for
        numbers) or ``predicate`` (a callable applied to the field).
        Returns a list of :class:`MaterialView`.
        """
        if (value is _UNSET) == (predicate is None):
            raise ValueError("pass exactly one of value or predicate")
        mf, mt, subpath = parse_section_path(section_path)
        matches = []
        for position, slot in enumerate(self._materials):
            if (mf, mt) not in self._slot_section_keys_set(slot):
                continue
            section = self._get_slot_section(slot, mf, mt)
            if isinstance(section, FailedSection):
                if self._on_error == "raise":
                    raise SectionParseError(
                        f"MF={mf}/MT={mt} of the material at position "
                        f"{position} failed to parse"
                    ) from section.exception
                continue
            if not section_has(section, subpath):
                continue
            field = walk_section(section, subpath)
            if predicate is not None:
                matched = bool(predicate(field))
            else:
                matched = _value_match(field, value, tol)
            if matched:
                matches.append(self[position])
        return matches

    @property
    def secondary_indexes(self):
        """The named secondary indexes built by :meth:`build_index`."""
        return self._secondary_indexes

    # -- per-material section access (slot-aware) ----------------------

    def _slot_section_keys_set(self, slot):
        if slot.original_position is not None:
            keys = set(self._index[slot.original_position].sections)
        else:
            keys = set()
        keys -= slot.deleted
        keys |= set(slot.overlay)
        return keys

    def _slot_section_keys(self, slot):
        return sorted(self._slot_section_keys_set(slot))

    def _get_slot_section(self, slot, mf, mt):
        key = (mf, mt)
        if key in slot.overlay:
            return slot.overlay[key]
        if key in slot.deleted:
            raise KeyError(f"this material has no MF={mf}/MT={mt} section")
        if (
            slot.original_position is None
            or key not in self._index[slot.original_position].sections
        ):
            raise KeyError(f"this material has no MF={mf}/MT={mt} section")
        return self._get_section(slot.original_position, mf, mt)

    def _set_slot_section(self, slot, mf, mt, value):
        if not isinstance(value, (Mapping, list)):
            raise TypeError(
                "a section must be a mapping (parsed) or a list of strings (raw)"
            )
        with self._lock:
            slot.overlay[(mf, mt)] = value
            slot.deleted.discard((mf, mt))

    def _delete_slot_section(self, slot, mf, mt):
        with self._lock:
            if (mf, mt) not in self._slot_section_keys_set(slot):
                raise KeyError(f"this material has no MF={mf}/MT={mt} section")
            slot.overlay.pop((mf, mt), None)
            if (
                slot.original_position is not None
                and (mf, mt) in self._index[slot.original_position].sections
            ):
                slot.deleted.add((mf, mt))

    # -- the lazy access path ------------------------------------------

    def _get_raw(self, position, mf, mt, sec_entry):
        key = (position, mf, mt)
        with self._lock:
            cached = self._raw_cache.get(key)
            if cached is not None:
                return cached
            raw = self._read_span(sec_entry.offset, sec_entry.length)
            self._raw_cache.put(key, raw, sec_entry.length)
            return raw

    def _get_section(self, position, mf, mt):
        key = (position, mf, mt)
        with self._lock:
            cached = self._section_cache.get(key)
            if cached is not None:
                return cached
            entry = self._index[position]
            sec_entry = entry.sections.get((mf, mt))
            if sec_entry is None:
                raise KeyError(
                    f"material at position {position} (MAT={entry.mat}) has "
                    f"no MF={mf}/MT={mt} section"
                )
            raw = self._get_raw(position, mf, mt, sec_entry)
            section = self._parse_section(entry, mf, mt, raw)
            self._section_cache.put(key, section, sec_entry.length)
            return section

    def _parse_section(self, entry, mf, mt, raw_lines):
        # wrap the section in a minimal single-material tape so the
        # ordinary parser can be used unchanged
        mini_tape = (
            [self._index.tpid_line]
            + list(raw_lines)
            + [
                _control_line(entry.mat, 0, 0),  # FEND
                _control_line(0, 0, 0),  # MEND
                _control_line(-1, 0, 0),  # TEND
            ]
        )
        try:
            result = self._parser.parse(mini_tape)
            section = result[mf][mt]
        except Exception as exc:
            if self._on_error == "raise":
                raise SectionParseError(
                    f"failed to parse MF={mf}/MT={mt} of the material at "
                    f"position {entry.position} (MAT={entry.mat})"
                ) from exc
            return FailedSection(exc, raw_lines, entry.position, mf, mt)
        if isinstance(section, Mapping):
            return _Section(section)
        return section  # a section without a recipe stays a list of strings

    def _read_span(self, offset, length):
        if self._verify_source:
            self._check_source()
        with open(self._path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(length)
        return data.decode("latin-1").splitlines()

    def _check_source(self):
        stat = os.stat(self._path)
        if (
            stat.st_size != self._index.source_size
            or stat.st_mtime_ns != self._index.source_mtime_ns
        ):
            raise StaleSourceError(
                f"the source file {self._path!r} changed after it was indexed"
            )

    # -- write-back ----------------------------------------------------

    def _assemble(self, slot):
        """Build a ``{MF: {MT: section}}`` dict ready for the writer.

        Untouched sections are taken verbatim from disk; edited or added
        sections come from the overlay.
        """
        material = {0: {0: [self._index.tpid_line]}}
        for mf, mt in self._slot_section_keys(slot):
            if (mf, mt) in slot.overlay:
                section = slot.overlay[(mf, mt)]
                if isinstance(section, FailedSection):
                    section = _strip_send(section.raw_lines)
                elif isinstance(section, list):
                    section = _strip_send(section)
            else:
                sec_entry = self._index[slot.original_position].sections[(mf, mt)]
                raw = self._get_raw(slot.original_position, mf, mt, sec_entry)
                section = _strip_send(raw)
            material.setdefault(mf, {})[mt] = section
        return material

    def save(self, out=None, *, overwrite=False):
        """Write the (possibly edited) tape.

        With ``out=None`` the assembled tape lines are returned. Given a
        path, the tape is written there via a temporary file and an
        atomic replace, so saving back onto the source file is safe.

        Untouched sections are written verbatim from disk; edited and
        added sections are rendered by the parser.
        """
        materials = [self._assemble(slot) for slot in self._materials]
        if out is None:
            return write_tape(materials, parser=self._parser)
        out = os.fspath(out)
        if os.path.exists(out) and not overwrite:
            raise FileExistsError(
                f"file {out} already exists; pass overwrite=True to replace it"
            )
        tmp = out + ".endfparserpy-tmp"
        write_tape(materials, tmp, parser=self._parser, overwrite=True)
        os.replace(tmp, out)
        return None

    # -- memory management ---------------------------------------------

    def unload(self, position=None):
        """Drop cached raw text and parsed sections.

        Edits held in the material overlays are not affected. With no
        argument the whole cache is cleared; given a material position,
        only that material's cached data is dropped.
        """
        with self._lock:
            if position is None:
                self._raw_cache.clear()
                self._section_cache.clear()
                return
            original = self._materials[position].original_position
            if original is not None:
                self._raw_cache.drop_material(original)
                self._section_cache.drop_material(original)

    @property
    def cache_nbytes(self):
        """The current ``(raw, parsed)`` cache sizes in bytes."""
        return self._raw_cache.nbytes, self._section_cache.nbytes

    @property
    def index(self):
        """The underlying :class:`TapeIndex` (describes the file on disk)."""
        return self._index

    @property
    def parser(self):
        """The parser engine used for sections."""
        return self._parser

    # -- context manager -----------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.unload()
        return False

    def __repr__(self):
        return f"<EndfFile {self._path!r}: {len(self._materials)} materials>"

    # -- pickling ------------------------------------------------------
    #
    # The index and the material slots (which carry any edits) are
    # pickled; the lock and caches are not, and the parser is recreated
    # from its backend name. Custom parser options are therefore not
    # preserved across pickling.

    def __getstate__(self):
        return {
            "path": self._path,
            "backend": self._backend,
            "on_error": self._on_error,
            "verify_source": self._verify_source,
            "raw_cache_bytes": self._raw_cache.max_bytes,
            "parsed_cache_bytes": self._section_cache.max_bytes,
            "index": self._index,
            "materials": self._materials,
        }

    def __setstate__(self, state):
        self._path = state["path"]
        self._backend = state["backend"]
        self._parser = EndfParserFactory.create(select=state["backend"])
        self._on_error = state["on_error"]
        self._verify_source = state["verify_source"]
        self._index = state["index"]
        self._materials = state["materials"]
        self._raw_cache = _RawCache(state["raw_cache_bytes"])
        self._section_cache = _SectionCache(state["parsed_cache_bytes"])
        self._material_views = {}
        self._secondary_indexes = {}
        self._lock = threading.RLock()
