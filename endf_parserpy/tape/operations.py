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

"""Eager multi-material parsing and writing of ENDF tapes.

These functions add support for ENDF files that contain several
materials (multi-material *tapes*, including PENDF/GENDF files that
repeat the same material at different temperatures). A tape is split
into single-material chunks by :func:`~endf_parserpy.tape.splitter.split_materials`
and each chunk is handed to an ordinary single-material parser. The
single-material parser itself is used unchanged.

Each operation comes as a pair, mirroring the ``parse`` / ``parsefile``
naming of the single-material parser: the bare name works on an
in-memory ENDF-6 string, the ``_file`` variant on a file path.
"""

import os

from ..endf_parser_factory import EndfParserFactory
from .splitter import split_materials, _control_numbers, TEND_LINE


_VALID_ON_ERROR = ("raise", "mark")


class FailedMaterial:
    """Placeholder for a material that could not be parsed.

    Returned by :func:`parse_tape` and :func:`iter_parse_tape` (and
    their ``_file`` variants) in place of a parsed material dictionary
    when ``on_error="mark"`` and the parsing of that material failed.
    Passing a :class:`FailedMaterial` back to :func:`write_tape` writes
    its original lines verbatim.

    Attributes
    ----------
    exception : Exception
        The exception raised while parsing the material.
    raw_lines : list[str]
        The lines of the single-material tape that failed to parse.
    """

    def __init__(self, exception, raw_lines):
        self.exception = exception
        self.raw_lines = list(raw_lines)

    @property
    def mat(self):
        """MAT number of the failed material, or ``None`` if unknown."""
        for line in self.raw_lines:
            mat, mf, mt = _control_numbers(line)
            if mat > 0 and mf > 0 and mt > 0:
                return mat
        return None

    def __repr__(self):
        return f"FailedMaterial(mat={self.mat}, exception={self.exception!r})"


def _ensure_parser(parser):
    if parser is None:
        return EndfParserFactory.create(select="fastest")
    return parser


def _check_on_error(on_error):
    if on_error not in _VALID_ON_ERROR:
        raise ValueError(f"on_error must be one of {_VALID_ON_ERROR}, got {on_error!r}")


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _iter_materials(lines, parser, exclude, include, on_error):
    """Split ``lines`` into materials and parse them one at a time."""
    for chunk in split_materials(lines):
        try:
            yield parser.parse(chunk, exclude=exclude, include=include)
        except Exception as exc:
            if on_error == "raise":
                raise
            yield FailedMaterial(exc, chunk)


def iter_parse_tape(text, *, parser=None, exclude=None, include=None, on_error="mark"):
    """Parse a multi-material ENDF tape, yielding one material at a time.

    Parameters
    ----------
    text : str
        The ENDF-6 formatted tape as a single string, as produced by
        :func:`write_tape` or :meth:`~endf_parserpy.EndfFile.to_string`.
        To parse a file on disk, use :func:`iter_parse_tape_file`.
    parser : EndfParserBase, optional
        The single-material parser used for each material. Defaults to
        ``EndfParserFactory.create(select="fastest")``.
    exclude, include : optional
        MF / (MF, MT) sections to exclude from / restrict the parsing
        to. Forwarded unchanged to the single-material parser and
        applied to every material.
    on_error : {"raise", "mark"}
        With ``"raise"`` the first material that fails to parse aborts
        the iteration. With ``"mark"`` (the default) a failing material
        is yielded as a :class:`FailedMaterial` and parsing continues.

    Yields
    ------
    dict or FailedMaterial
        The parsed material dictionary (same shape as the result of a
        single-material ``parsefile``), or a :class:`FailedMaterial`.

    Notes
    -----
    Only one material is held in parsed form at a time, so the parsed
    data does not accumulate; for a tape too large to hold in memory at
    all, parse it from disk with :func:`iter_parse_tape_file`.
    """
    _check_on_error(on_error)
    parser = _ensure_parser(parser)
    yield from _iter_materials(text.splitlines(), parser, exclude, include, on_error)


def iter_parse_tape_file(
    path, *, parser=None, exclude=None, include=None, on_error="mark"
):
    """Parse a multi-material ENDF tape from a file, one material at a time.

    The file counterpart of :func:`iter_parse_tape`; the ``path``
    argument is a file path (``str`` or :class:`os.PathLike`). The file
    is read incrementally, so peak memory use is bounded by the largest
    single material rather than by the size of the whole tape. See
    :func:`iter_parse_tape` for the remaining parameters.
    """
    _check_on_error(on_error)
    parser = _ensure_parser(parser)
    with open(os.fspath(path), "r") as fh:
        yield from _iter_materials(fh, parser, exclude, include, on_error)


def parse_tape(text, *, parser=None, exclude=None, include=None, on_error="mark"):
    """Parse a multi-material ENDF tape string into a list of materials.

    This is the eager counterpart of :func:`iter_parse_tape`; see there
    for a description of the parameters. To parse a file on disk, use
    :func:`parse_tape_file`.

    Returns
    -------
    list
        One entry per material, in tape order. Each entry is either a
        parsed material dictionary or, for a material that failed to
        parse with ``on_error="mark"``, a :class:`FailedMaterial`.
    """
    return list(
        iter_parse_tape(
            text, parser=parser, exclude=exclude, include=include, on_error=on_error
        )
    )


def parse_tape_file(path, *, parser=None, exclude=None, include=None, on_error="mark"):
    """Parse a multi-material ENDF tape file into a list of materials.

    The file counterpart of :func:`parse_tape`; the ``path`` argument is
    a file path (``str`` or :class:`os.PathLike`). See :func:`parse_tape`
    for the return value and :func:`iter_parse_tape` for the parameters.
    """
    return list(
        iter_parse_tape_file(
            path, parser=parser, exclude=exclude, include=include, on_error=on_error
        )
    )


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def _strip_trailing_tend(lines):
    """Drop a trailing TEND record; return ``(lines, tend_or_None)``."""
    if lines:
        mat, _, _ = _control_numbers(lines[-1])
        if mat == -1:
            return lines[:-1], lines[-1]
    return lines, None


def _strip_leading_tpid(lines):
    """Drop a leading TPID record; return ``(lines, tpid_or_None)``."""
    if lines:
        _, mf, mt = _control_numbers(lines[0])
        if mf == 0 and mt == 0:
            return lines[1:], lines[0]
    return lines, None


def _material_lines(material, parser, exclude, include):
    if isinstance(material, FailedMaterial):
        return list(material.raw_lines)
    return parser.write(material, exclude=exclude, include=include)


def _assemble_tape_lines(materials, parser, exclude, include):
    """Assemble materials into the lines of a single multi-material tape.

    Each material is written with an ordinary single-material parser;
    the resulting per-material tape head (TPID) and tape end (TEND)
    records are stripped so that the combined tape carries the TPID once
    at the start, every material followed by its MEND record, and a
    single TEND record at the end.
    """
    parser = _ensure_parser(parser)
    body = []
    tpid_line = None
    final_tend = None
    for material in materials:
        lines = _material_lines(material, parser, exclude, include)
        lines, tend = _strip_trailing_tend(lines)
        if tend is not None:
            final_tend = tend
        lines, tpid = _strip_leading_tpid(lines)
        if tpid is not None and tpid_line is None:
            tpid_line = tpid
        body.extend(lines)

    result = []
    if tpid_line is not None:
        result.append(tpid_line)
    result.extend(body)
    result.append(final_tend if final_tend is not None else TEND_LINE)
    return result


def write_tape(materials, *, parser=None, exclude=None, include=None):
    """Assemble materials into a single multi-material ENDF tape string.

    A :class:`FailedMaterial` is written verbatim from its stored lines.

    Parameters
    ----------
    materials : Iterable
        Parsed material dictionaries and/or :class:`FailedMaterial`
        objects, in the desired tape order.
    parser : EndfParserBase, optional
        Parser used to write each material. Defaults to
        ``EndfParserFactory.create(select="fastest")``.
    exclude, include : optional
        Forwarded unchanged to the single-material parser's ``write``.

    Returns
    -------
    str
        The assembled tape as a single ENDF-6 formatted string, ending
        with a newline. To write a file instead, use
        :func:`write_tape_file`.
    """
    lines = _assemble_tape_lines(materials, parser, exclude, include)
    return "\n".join(lines) + "\n"


def write_tape_file(
    materials, path, *, parser=None, exclude=None, include=None, overwrite=False
):
    """Assemble materials and write the tape to a file.

    The file counterpart of :func:`write_tape`; ``path`` is a file path
    (``str`` or :class:`os.PathLike`). An existing file is only
    overwritten when ``overwrite=True``. See :func:`write_tape` for the
    remaining parameters.
    """
    path = os.fspath(path)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(
            f"file {path} already exists; pass overwrite=True to replace it"
        )
    lines = _assemble_tape_lines(materials, parser, exclude, include)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
