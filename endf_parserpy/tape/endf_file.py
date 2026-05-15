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

"""Lazy, memory-bounded access to a multi-material ENDF file.

:class:`EndfFile` indexes a tape on construction and reads and parses
individual sections from disk only when they are accessed, keeping the
results in bounded caches (see :mod:`endf_parserpy.tape.cache`). A
single section is parsed by wrapping its records in a minimal
single-material tape and handing that to an ordinary parser, so the
parsing engine is used unchanged.
"""

import os
import threading
from collections.abc import Mapping

from ..endf_parser_factory import EndfParserFactory
from .cache import _RawCache, _SectionCache, _Section
from .errors import AmbiguousMaterialError, SectionParseError, StaleSourceError
from .index import TapeIndex
from .material import MaterialView


_VALID_MODES = ("index", "load_raw", "parse_all")
_VALID_ON_ERROR = ("raise", "mark")
_BACKEND_OF = {"EndfParserCpp": "cpp", "EndfParserPy": "python"}


def _control_line(mat, mf, mt):
    """Build a control-only ENDF record (used for FEND/MEND/TEND)."""
    return " " * 66 + f"{mat:>4}{mf:>2}{mt:>3}"


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
    """Lazy, memory-bounded view of a multi-material ENDF file.

    The file is indexed on construction (see :class:`TapeIndex`).
    Section data is read from disk and parsed only on access and is then
    held in bounded caches. Materials are addressed by zero-based
    position::

        with EndfFile("tape.endf") as endf_file:
            material = endf_file[0]         # a MaterialView
            section = material[3, 2]        # parsed MF=3/MT=2 section

    Parameters
    ----------
    filename : str or os.PathLike
        Path to the ENDF file.
    parser : EndfParserBase, optional
        Engine used to parse individual sections. Defaults to
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
        self._raw_cache = _RawCache(raw_cache_bytes)
        self._section_cache = _SectionCache(parsed_cache_bytes)
        self._material_views = {}
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
        return len(self._index)

    def __getitem__(self, position):
        if not isinstance(position, int):
            raise TypeError(
                "EndfFile is indexed by integer material position; use "
                "by_mat() or by_za() for other lookups"
            )
        entry = self._index[position]
        view = self._material_views.get(entry.position)
        if view is None:
            view = MaterialView(self, entry)
            self._material_views[entry.position] = view
        return view

    def __iter__(self):
        for position in range(len(self._index)):
            yield self[position]

    def materials(self):
        """Return all materials as a list of :class:`MaterialView` objects."""
        return list(self)

    # -- secondary lookups ---------------------------------------------

    def by_mat(self, mat, *, occurrence=None):
        """Return the material with the given MAT number.

        ``occurrence`` (zero-based) selects among several materials that
        share a MAT number, as on a PENDF tape. Without it, a MAT number
        that is not unique raises :class:`AmbiguousMaterialError`.
        """
        positions = self._index.by_mat(mat)
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
        return [self[p] for p in self._index.by_za(za)]

    def find(self, *, mat=None, za=None):
        """Return a list of materials matching every given criterion."""
        positions = set(range(len(self._index)))
        if mat is not None:
            positions &= set(self._index.by_mat(mat))
        if za is not None:
            positions &= set(self._index.by_za(za))
        return [self[p] for p in sorted(positions)]

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

    # -- memory management ---------------------------------------------

    def unload(self, position=None):
        """Drop cached raw text and parsed sections.

        With no argument the whole cache is cleared; given a material
        position, only that material's cached data is dropped.
        """
        with self._lock:
            if position is None:
                self._raw_cache.clear()
                self._section_cache.clear()
            else:
                self._raw_cache.drop_material(position)
                self._section_cache.drop_material(position)

    @property
    def cache_nbytes(self):
        """The current ``(raw, parsed)`` cache sizes in bytes."""
        return self._raw_cache.nbytes, self._section_cache.nbytes

    @property
    def index(self):
        """The underlying :class:`TapeIndex`."""
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
        return f"<EndfFile {self._path!r}: {len(self._index)} materials>"

    # -- pickling ------------------------------------------------------
    #
    # The index (the expensive part) is pickled so that worker processes
    # need not re-scan the file. The lock and caches are not pickled and
    # the parser is recreated from its backend name; custom parser
    # options are therefore not preserved across pickling.

    def __getstate__(self):
        return {
            "path": self._path,
            "backend": self._backend,
            "on_error": self._on_error,
            "verify_source": self._verify_source,
            "raw_cache_bytes": self._raw_cache.max_bytes,
            "parsed_cache_bytes": self._section_cache.max_bytes,
            "index": self._index,
        }

    def __setstate__(self, state):
        self._path = state["path"]
        self._backend = state["backend"]
        self._parser = EndfParserFactory.create(select=state["backend"])
        self._on_error = state["on_error"]
        self._verify_source = state["verify_source"]
        self._index = state["index"]
        self._raw_cache = _RawCache(state["raw_cache_bytes"])
        self._section_cache = _SectionCache(state["parsed_cache_bytes"])
        self._material_views = {}
        self._lock = threading.RLock()
