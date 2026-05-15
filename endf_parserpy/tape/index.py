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
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .errors import TapeStructureError
from .splitter import _control_numbers


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


def _iter_byte_records(fh):
    """Yield ``(offset, byte_length, text)`` for each line of a binary file."""
    offset = 0
    for raw in fh:
        yield offset, len(raw), raw.decode("latin-1")
        offset += len(raw)


def _iter_line_records(lines):
    """Yield ``(offset, byte_length, text)`` for an iterable of strings.

    Byte offsets are computed assuming a single ``"\\n"`` terminates
    each line. They are therefore only exact for a file written that
    way; use :meth:`TapeIndex.from_file` when exact on-disk offsets are
    required.
    """
    offset = 0
    for line in lines:
        line = line.rstrip("\r\n")
        byte_length = len(line.encode("latin-1", errors="replace")) + 1
        yield offset, byte_length, line
        offset += byte_length


def _scan(records):
    """Scan ``records`` into ``(materials, (tpid_line, offset, length))``."""
    materials = []
    tpid = None

    # the tape head (TPID) is the first non-blank record
    for offset, byte_length, text in records:
        if text.strip() == "":
            continue
        _, mf, mt = _control_numbers(text)
        if mf != 0 or mt != 0:
            raise TapeStructureError(
                "the tape does not begin with a tape head (TPID) record "
                f"(found MF={mf}, MT={mt})"
            )
        tpid = (text.rstrip("\r\n"), offset, byte_length)
        break
    if tpid is None:
        raise TapeStructureError("the tape does not contain any records")

    cur = None  # material under construction
    sec_key = None  # (MF, MT) of the section under construction
    sec_offset = sec_length = sec_lines = 0

    def flush_section():
        # store a section that was left open (e.g. a missing SEND record)
        nonlocal sec_key
        if sec_key is not None and cur is not None:
            cur["sections"][sec_key] = SectionIndexEntry(
                sec_offset, sec_length, sec_lines
            )
        sec_key = None

    for offset, byte_length, text in records:
        if text.strip() == "":
            continue
        mat, mf, mt = _control_numbers(text)
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
                cur["za"], cur["awr"] = _read_za_awr(text)
            if (mf, mt) != sec_key:
                flush_section()
                sec_key = (mf, mt)
                sec_offset = offset
                sec_length = 0
                sec_lines = 0
            sec_length += byte_length
            sec_lines += 1
            continue
        if mf != 0 and mt == 0:  # SEND: end of section
            if sec_key is not None and cur is not None:
                cur["sections"][sec_key] = SectionIndexEntry(
                    sec_offset, sec_length + byte_length, sec_lines + 1
                )
            sec_key = None
            continue
        if mat == 0 and mf == 0 and mt == 0:  # MEND: end of material
            flush_section()
            if cur is not None:
                cur["byte_length"] = offset + byte_length - cur["byte_offset"]
                materials.append(MaterialIndexEntry(**cur))
                cur = None
            continue
        # FEND (mat > 0, mf == 0, mt == 0) or any other record: a section
        # cannot continue across it
        flush_section()

    if cur is not None:
        raise TapeStructureError(
            "the tape ends in the middle of a material; the final MEND or "
            "TEND record is missing"
        )
    return materials, tpid


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
            materials, tpid = _scan(_iter_byte_records(fh))
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
        """Build an index from an iterable of ENDF tape lines."""
        materials, tpid = _scan(_iter_line_records(lines))
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
