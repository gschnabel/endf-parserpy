############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/16
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Lexically split a multi-material ENDF tape into single-material tapes.

An ENDF *tape* may contain several materials. Each material is terminated
by a MEND record and the whole tape by a TEND record. This module splits
such a tape into chunks, where each chunk is itself a valid single-material
tape (tape head + one material + tape end) that can be handed to an
ordinary single-material parser.

The splitting is purely lexical: only the MAT/MF/MT control fields in
columns 67-75 of each line are inspected. No ENDF recipe is consulted and
the content of the records is never interpreted.
"""

from .errors import TapeStructureError


# A tape end (TEND) record: MAT=-1, MF=0, MT=0, all value fields blank.
# This synthetic record is only ever used as input to a single-material
# parser, so no trailing sequence number is required.
TEND_LINE = " " * 66 + "  -1 0  0"

# A default tape head (TPID) record: a blank 66-column label followed by
# MAT=1, MF=0, MT=0. Emitted when a tape is assembled from materials
# that carry no TPID of their own, so that an assembled tape -- an empty
# one included -- always begins with a valid TPID record.
DEFAULT_TPID_LINE = " " * 66 + "   1 0  0"

# The MAT/MF/MT control fields occupy fixed columns of every ENDF
# record: MAT in columns 67-70, MF in 71-72 and MT in 73-75. These
# zero-based byte slices are the single definition of that layout,
# used here and by the structural scanner in index.py.
_MAT_COLS = slice(66, 70)
_MF_COLS = slice(70, 72)
_MT_COLS = slice(72, 75)
_CTRL_COLS = slice(66, 75)


def _control_int(field):
    """Parse an integer from a MAT/MF/MT control field.

    A blank or non-numeric field reads as zero, consistent with the
    ENDF convention for blank control fields. Accepts ``str`` or
    ``bytes`` -- ``int()`` handles both and strips surrounding spaces.
    """
    try:
        return int(field)
    except ValueError:
        return 0


def _control_numbers(line):
    """Return the ``(MAT, MF, MT)`` integers of an ENDF line.

    The control fields occupy columns 67-70 (MAT), 71-72 (MF) and
    73-75 (MT). Blank or non-numeric control fields are interpreted as
    zero, consistent with how blank control fields are treated
    throughout ENDF-6.
    """
    return (
        _control_int(line[_MAT_COLS]),
        _control_int(line[_MF_COLS]),
        _control_int(line[_MT_COLS]),
    )


def split_materials(lines):
    """Yield single-material tapes from a multi-material ENDF tape.

    Parameters
    ----------
    lines : Iterable[str]
        The lines of a (possibly multi-material) ENDF tape. May be a
        list, an open file object, or any other iterable of strings.
        Trailing line breaks are stripped.

    Yields
    ------
    list[str]
        For each material on the tape, a list of lines forming a
        self-contained single-material tape: the tape head (TPID)
        record, the material's records (including its MEND record)
        and a tape end (TEND) record.

    Raises
    ------
    TapeStructureError
        If the tape does not begin with a TPID record, or if it ends
        in the middle of a material.

    Notes
    -----
    Blank lines (e.g. padding between materials) are not preserved.
    """
    line_iter = iter(lines)

    # locate the tape head (TPID): the first non-blank record
    tpid = None
    for raw in line_iter:
        line = raw.rstrip("\r\n")
        if line.strip() == "":
            continue
        tpid = line
        break
    if tpid is None:
        raise TapeStructureError("the tape does not contain any records")

    mat, mf, mt = _control_numbers(tpid)
    if mat < 0 or mf != 0 or mt != 0:
        raise TapeStructureError(
            "the tape does not begin with a tape head (TPID) record "
            f"(found MAT={mat}, MF={mf}, MT={mt}); a multi-material tape "
            "must start with a TPID record"
        )

    current = []
    for raw in line_iter:
        line = raw.rstrip("\r\n")
        if line.strip() == "":
            # inter-material and padding blank lines are not preserved
            continue
        mat, mf, mt = _control_numbers(line)
        if mat == -1:
            # tape end (TEND) record: nothing meaningful follows
            break
        current.append(line)
        if mat == 0 and mf == 0 and mt == 0:
            # MEND record: the current material is complete
            if len(current) > 1:
                yield [tpid] + current + [TEND_LINE]
            current = []

    if current:
        raise TapeStructureError(
            "the tape ends in the middle of a material; the final "
            "MEND or TEND record is missing"
        )
