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

"""Structural index of a multi-material ENDF tape.

The index records, for every material on a tape, its MAT number, the
ZA/AWR identifiers read from the first HEAD record, the byte range it
occupies in the file and the byte range of every (MF, MT) section it
contains.

It is built by a single linear scan that inspects only the *structural*
parts of the ENDF-6 format: the MAT/MF/MT control fields (columns
67-75) and the universal HEAD-record layout (``C1=ZA``, ``C2=AWR``). No
ENDF recipe is consulted and no section body is interpreted, so the
index is cheap to build and completely independent of the parsing
engine.

When ``numpy`` is installed and the tape is a uniform array of
fixed-width records (the common case), a vectorized fast path is used
that extracts every record's control field in one bulk operation; it
produces an index identical to the linear scan and falls back to it for
any tape that is not uniform-width.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .errors import TapeStructureError

try:
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is an optional accelerator
    _np = None


def _endf_float(field_text):
    """Parse an 11-column ENDF number field; return ``None`` on failure.

    ENDF numbers may use an implicit exponent, e.g. ``9.223800+4`` for
    ``9.223800e+4``. ``None`` is returned rather than raising, so that
    an unparsable identifier field never aborts an index build.
    """
    text = field_text.strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        pass
    # implicit-exponent form: a sign that is neither the leading sign
    # nor preceded by 'e'/'E' marks the start of the exponent
    for i in range(len(text) - 1, 0, -1):
        if text[i] in "+-" and text[i - 1] not in "eE":
            try:
                return float(text[:i] + "e" + text[i:])
            except ValueError:
                return None
    return None


def _read_za_awr(line):
    """Read ``(ZA, AWR)`` from the C1/C2 fields of a HEAD record."""
    za = _endf_float(line[0:11])
    awr = _endf_float(line[11:22])
    za_int = int(round(za)) if za is not None else None
    return za_int, awr


@dataclass
class SectionIndexEntry:
    """Location of one (MF, MT) section within the tape file.

    Attributes
    ----------
    offset : int
        Byte offset of the section's first record.
    length : int
        Total byte length of the section, including its SEND record.
    line_count : int
        Number of records in the section, including its SEND record.
    """

    offset: int
    length: int
    line_count: int


@dataclass
class MaterialIndexEntry:
    """Location and identity of one material on the tape.

    Instances are intended to be treated as read-only.

    Attributes
    ----------
    position : int
        Zero-based position of the material on the tape; this is the
        material's canonical identity (see design decision D1).
    mat : int
        ENDF MAT number. Not unique: PENDF/GENDF tapes repeat the same
        MAT at different temperatures.
    za : int or None
        ZA identifier (``1000*Z + A``) from the first HEAD record, or
        ``None`` if it could not be read.
    awr : float or None
        Atomic weight ratio from the first HEAD record, or ``None``.
    byte_offset : int
        Byte offset of the material's first record.
    byte_length : int
        Total byte length of the material, including its MEND record.
    sections : dict[tuple[int, int], SectionIndexEntry]
        The (MF, MT) sections contained in the material.
    """

    position: int
    mat: int
    za: Optional[int]
    awr: Optional[float]
    byte_offset: int
    byte_length: int
    sections: Dict[Tuple[int, int], SectionIndexEntry] = field(default_factory=dict)


def _fast_int(field):
    """Parse an integer from a byte control field.

    A blank or non-numeric field reads as zero, consistent with the
    ENDF convention for blank control fields.
    """
    field = field.strip()
    if not field:
        return 0
    try:
        return int(field)
    except ValueError:
        return 0


def _scan(data):
    """Scan raw tape bytes into ``(materials, (tpid_line, offset, length))``.

    Only the structural fields are read. The MAT/MF/MT control fields
    occupy the fixed byte slice ``[66:75]`` of every record; since all
    records of a section share that slice, a record whose slice is
    unchanged from its predecessor is known to continue the current
    section and is accumulated without parsing any integer. This fast
    path covers the great majority of records.

    Records are delimited by ``"\\n"`` only, matching binary-mode file
    iteration; a trailing ``"\\r"`` is part of the record's bytes and
    is stripped only where the text is actually needed.
    """
    parts = data.split(b"\n")
    nparts = len(parts)

    materials = []
    cur = None  # material under construction
    sec_key = None  # (MF, MT) of the section under construction
    sec_offset = sec_length = sec_lines = 0
    prev_ctrl = None  # the [66:75] control slice of the previous record

    def flush_section():
        # store a section that was left open (e.g. a missing SEND record)
        nonlocal sec_key
        if sec_key is not None and cur is not None:
            cur["sections"][sec_key] = SectionIndexEntry(
                sec_offset, sec_length, sec_lines
            )
        sec_key = None

    offset = 0
    tpid = None
    index = 0

    # the tape head (TPID) is the first non-blank record
    while index < nparts:
        part = parts[index]
        last = index + 1 == nparts
        if last and not part:
            break
        byte_length = len(part) + (0 if last else 1)
        if part.strip():
            mf = _fast_int(part[70:72])
            mt = _fast_int(part[72:75])
            if mf != 0 or mt != 0:
                raise TapeStructureError(
                    "the tape does not begin with a tape head (TPID) "
                    f"record (found MF={mf}, MT={mt})"
                )
            tpid = (part.rstrip(b"\r").decode("latin-1"), offset, byte_length)
            offset += byte_length
            index += 1
            break
        offset += byte_length
        index += 1
    if tpid is None:
        raise TapeStructureError("the tape does not contain any records")

    while index < nparts:
        part = parts[index]
        last = index + 1 == nparts
        if last and not part:
            break
        byte_length = len(part) + (0 if last else 1)
        ctrl = part[66:75]

        # fast path: the control fields are unchanged, so this record
        # continues the section currently under construction
        if ctrl == prev_ctrl:
            sec_length += byte_length
            sec_lines += 1
            offset += byte_length
            index += 1
            continue

        if not part.strip():  # blank padding record
            offset += byte_length
            index += 1
            continue

        mat = _fast_int(ctrl[0:4])
        mf = _fast_int(ctrl[4:6])
        mt = _fast_int(ctrl[6:9])

        if mat == -1:  # TEND: end of tape
            break
        if mat > 0 and mf > 0 and mt > 0:  # regular record
            if cur is None:
                cur = {
                    "position": len(materials),
                    "mat": mat,
                    "byte_offset": offset,
                    "sections": {},
                }
                cur["za"], cur["awr"] = _read_za_awr(part.decode("latin-1"))
            if (mf, mt) != sec_key:
                flush_section()
                sec_key = (mf, mt)
                sec_offset = offset
                sec_length = 0
                sec_lines = 0
            sec_length += byte_length
            sec_lines += 1
            prev_ctrl = ctrl
        elif mf != 0 and mt == 0:  # SEND: end of section
            if sec_key is not None and cur is not None:
                cur["sections"][sec_key] = SectionIndexEntry(
                    sec_offset, sec_length + byte_length, sec_lines + 1
                )
            sec_key = None
            prev_ctrl = None
        elif mat == 0 and mf == 0 and mt == 0:  # MEND: end of material
            flush_section()
            if cur is not None:
                cur["byte_length"] = offset + byte_length - cur["byte_offset"]
                materials.append(MaterialIndexEntry(**cur))
                cur = None
            prev_ctrl = None
        else:  # FEND (mat > 0, mf == 0, mt == 0), or any other record
            # a section cannot continue across such a record
            flush_section()
            prev_ctrl = None

        offset += byte_length
        index += 1

    if cur is not None:
        raise TapeStructureError(
            "the tape ends in the middle of a material; the final MEND or "
            "TEND record is missing"
        )
    return materials, tpid


def _vec_scan(data):
    """Vectorized structural scan for a uniform fixed-width tape.

    Return ``(materials, tpid)`` on a clean parse of a tape that is a
    uniform array of fixed-width records, or ``None`` for any tape that
    is not uniform-width or not cleanly structured. In the latter case
    the caller falls back to :func:`_scan`, which is the authority for
    both the index and any structural error.

    The record width ``L`` is inferred from the first newline and then
    *proven* uniform: the buffer is reshaped to an ``(N, L)`` matrix and
    column ``L-1`` is required to be a newline on every row. The control
    field of every record is the byte slice ``[66:75]``; a section or
    material boundary is exactly a row whose control field differs from
    its predecessor, so the per-record scan collapses into a loop over
    *runs* of identical control fields.

    A tape whose only irregularity is an unterminated final TEND record
    and/or a few trailing blank lines is still accepted: the partial
    trailing record (always shorter than one record) is trimmed before
    the width check, since nothing past the last material affects the
    index. The trim is gated on the tail being benign -- only
    whitespace, or a TEND record -- so a genuinely truncated record is
    never silently dropped.
    """
    n = len(data)
    if n == 0:
        return None
    first_nl = data.find(b"\n")
    if first_nl < 0:
        return None
    line_width = first_nl + 1
    # the control field ends at column 75, so a record must be wide
    # enough to contain it
    if line_width < 76:
        return None
    remainder = n % line_width
    if remainder:
        # the tape does not end on a record boundary -- typically an
        # unterminated TEND record and/or trailing blank lines. Trim the
        # partial trailing record so the uniform body before it can
        # still take the fast path, but only if that tail is benign
        # (whitespace, or a TEND record); a non-benign tail is a
        # truncated record and is left for the linear scan to judge.
        tail = data[n - remainder :]
        if tail.strip() and _fast_int(tail[66:70]) != -1:
            return None
        data = data[: n - remainder]
        n -= remainder
    num_lines = n // line_width
    arr = _np.frombuffer(data, dtype=_np.uint8).reshape(num_lines, line_width)
    # certain fixed-width check: the last byte of every record is "\n"
    if not bool(_np.all(arr[:, line_width - 1] == 0x0A)):
        return None

    ctrl = arr[:, 66:75]  # the MAT/MF/MT control field of every record

    # the TPID is the first record with a non-blank control field
    nonblank = _np.any(ctrl != 0x20, axis=1)
    if not bool(_np.any(nonblank)):
        return None
    tpid_row = int(_np.argmax(nonblank))
    if tpid_row and data[: tpid_row * line_width].strip():
        return None  # non-blank content before the TPID
    head = ctrl[tpid_row].tobytes()
    if _fast_int(head[4:6]) != 0 or _fast_int(head[6:9]) != 0:
        return None  # does not begin with a TPID record
    tpid_offset = tpid_row * line_width
    tpid = (
        data[tpid_offset : tpid_offset + line_width].rstrip(b"\r\n").decode("latin-1"),
        tpid_offset,
        line_width,
    )

    # run-segment every record after the TPID
    body = ctrl[tpid_row + 1 :]
    if len(body) == 0:
        return [], tpid
    boundary = _np.any(body[1:] != body[:-1], axis=1)
    starts = _np.concatenate(([0], _np.flatnonzero(boundary) + 1)) + tpid_row + 1
    ends = _np.concatenate((starts[1:], [num_lines]))

    materials = []
    cur = None
    sec_key = None
    sec_offset = sec_length = sec_lines = 0

    def flush_section():
        nonlocal sec_key
        if sec_key is not None and cur is not None:
            cur["sections"][sec_key] = SectionIndexEntry(
                sec_offset, sec_length, sec_lines
            )
        sec_key = None

    for start, end in zip(starts.tolist(), ends.tolist()):
        ctrl_field = ctrl[start].tobytes()
        run_offset = start * line_width
        run_length = (end - start) * line_width
        if not ctrl_field.strip():  # blank-control run
            if data[run_offset : end * line_width].strip():
                return None  # a record carrying data but a blank control field
            continue
        mat = _fast_int(ctrl_field[0:4])
        mf = _fast_int(ctrl_field[4:6])
        mt = _fast_int(ctrl_field[6:9])
        if mat == -1:  # TEND: end of tape
            break
        if mat > 0 and mf > 0 and mt > 0:  # a run of regular section records
            if cur is None:
                cur = {
                    "position": len(materials),
                    "mat": mat,
                    "byte_offset": run_offset,
                    "sections": {},
                }
                cur["za"], cur["awr"] = _read_za_awr(
                    data[run_offset : run_offset + line_width].decode("latin-1")
                )
            if (mf, mt) != sec_key:
                flush_section()
                sec_key = (mf, mt)
                sec_offset = run_offset
                sec_length = 0
                sec_lines = 0
            sec_length += run_length
            sec_lines += end - start
        elif mf != 0 and mt == 0:  # SEND: end of section
            if sec_key is not None and cur is not None:
                cur["sections"][sec_key] = SectionIndexEntry(
                    sec_offset, sec_length + run_length, sec_lines + (end - start)
                )
            sec_key = None
        elif mat == 0 and mf == 0 and mt == 0:  # MEND: end of material
            flush_section()
            if cur is not None:
                cur["byte_length"] = end * line_width - cur["byte_offset"]
                materials.append(MaterialIndexEntry(**cur))
                cur = None
        else:  # FEND, or any other record a section cannot span
            flush_section()

    if cur is not None:
        return None  # truncated tape -- let _scan raise the structural error
    return materials, tpid


def _scan_data(data):
    """Scan raw tape bytes, using the vectorized fast path when possible."""
    if _np is not None:
        result = _vec_scan(data)
        if result is not None:
            return result
    return _scan(data)


class TapeIndex:
    """A structural index over the materials of an ENDF tape.

    Build one with :meth:`from_file` (exact on-disk byte offsets) or
    :meth:`from_lines`. The index supports ``len()``, iteration and
    integer position indexing, and provides :meth:`by_mat` and
    :meth:`by_za` secondary lookups. It is recipe-free and picklable.

    Attributes
    ----------
    materials : list[MaterialIndexEntry]
        The materials, in tape order.
    tpid_line : str
        The tape head (TPID) record.
    tpid_offset, tpid_length : int
        Byte location of the TPID record.
    source : str or None
        Path of the indexed file, if built with :meth:`from_file`.
    source_size, source_mtime_ns : int or None
        Size and modification time of the source file at index time;
        usable to detect that the file changed after indexing.
    """

    def __init__(
        self,
        materials,
        tpid_line,
        tpid_offset,
        tpid_length,
        source=None,
        source_size=None,
        source_mtime_ns=None,
    ):
        self.materials = list(materials)
        self.tpid_line = tpid_line
        self.tpid_offset = tpid_offset
        self.tpid_length = tpid_length
        self.source = source
        self.source_size = source_size
        self.source_mtime_ns = source_mtime_ns
        self._by_mat = {}
        self._by_za = {}
        for entry in self.materials:
            self._by_mat.setdefault(entry.mat, []).append(entry.position)
            if entry.za is not None:
                self._by_za.setdefault(entry.za, []).append(entry.position)

    @classmethod
    def from_file(cls, path):
        """Build an index of the ENDF tape stored at ``path``."""
        path = os.fspath(path)
        with open(path, "rb") as fh:
            data = fh.read()
        materials, tpid = _scan_data(data)
        stat = os.stat(path)
        return cls(
            materials,
            tpid[0],
            tpid[1],
            tpid[2],
            source=path,
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
        )

    @classmethod
    def from_lines(cls, lines, source=None):
        """Build an index from an iterable of ENDF tape lines.

        Byte offsets are computed assuming a single ``"\\n"`` terminates
        each line; they are therefore only exact for a file written
        that way. Use :meth:`from_file` when exact on-disk offsets are
        required.
        """
        data = (
            b"\n".join(
                line.rstrip("\r\n").encode("latin-1", errors="replace")
                for line in lines
            )
            + b"\n"
        )
        materials, tpid = _scan_data(data)
        return cls(materials, tpid[0], tpid[1], tpid[2], source=source)

    def by_mat(self, mat):
        """Return the positions of all materials with this MAT number."""
        return list(self._by_mat.get(mat, ()))

    def by_za(self, za):
        """Return the positions of all materials with this ZA identifier."""
        return list(self._by_za.get(za, ()))

    def __len__(self):
        return len(self.materials)

    def __iter__(self):
        return iter(self.materials)

    def __getitem__(self, position):
        return self.materials[position]

    def __repr__(self):
        source = f", source={self.source!r}" if self.source else ""
        return f"TapeIndex({len(self.materials)} materials{source})"
