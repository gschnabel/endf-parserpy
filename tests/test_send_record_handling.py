############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/13
# Last modified:   2026/05/18
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Tests for the `ignore_send_records` parsing flag and end-of-tape
completeness checks (SEND/FEND/MEND/TEND nesting) in both the C++ and
pure-Python backends. Regression coverage for issue #57 where the C++
parser silently accepted tapes truncated before MEND/TEND.
"""

import pytest
from endf_parserpy import EndfParserCpp, EndfParserPy, EndfDict


PARSER_CLASSES = [EndfParserCpp, EndfParserPy]


def _build_minimal_endf_text(parser_for_writing):
    """Build a syntactically valid one-section ENDF tape and return it as
    a single string. Uses MF=3/MT=2 so the recipe surface stays small.
    """
    d = EndfDict()
    d["3/2"] = {}
    sec = d["3/2"]
    sec["MAT"] = 2625
    sec["MF"] = 3
    sec["MT"] = 2
    sec["ZA"] = 26054.0
    sec["AWR"] = 53.47
    sec["QM"] = 0.0
    sec["QI"] = 0.0
    sec["LR"] = 0
    sec["xstable/E"] = [1.0, 2.0]
    sec["xstable/xs"] = [10.0, 20.0]
    sec["xstable/NBT"] = [2]
    sec["xstable/INT"] = [2]
    text = parser_for_writing.write(d.unwrap())
    if isinstance(text, list):
        text = "\n".join(text) + "\n"
    return text


def _strip_trailing_record(text, n):
    """Drop the last `n` non-empty lines (each ENDF terminator is one line)."""
    lines = text.rstrip("\n").splitlines()
    return "\n".join(lines[:-n]) + "\n"


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_well_formed_tape_passes_strict(ParserCls, tmp_path):
    """Sanity baseline: a complete tape with proper SEND/FEND/MEND/TEND
    closure parses cleanly when end-record checking is strict."""
    parser = ParserCls(ignore_missing_tpid=True)
    text = _build_minimal_endf_text(parser)
    fp = tmp_path / "complete.endf"
    fp.write_bytes(text.encode("latin-1"))
    strict = ParserCls(ignore_missing_tpid=True, ignore_send_records=False)
    strict.parsefile(str(fp))


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_missing_mend_and_tend_rejected_strict(ParserCls, tmp_path):
    """Tape ends after FEND, with MEND and TEND missing — strict mode must
    reject. Reproduction of issue #57."""
    parser = ParserCls(ignore_missing_tpid=True)
    text = _build_minimal_endf_text(parser)
    truncated = _strip_trailing_record(text, 2)  # drop MEND + TEND
    fp = tmp_path / "no_mend_tend.endf"
    fp.write_bytes(truncated.encode("latin-1"))
    strict = ParserCls(ignore_missing_tpid=True, ignore_send_records=False)
    with pytest.raises(Exception):
        strict.parsefile(str(fp))


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_missing_tend_only_rejected_strict(ParserCls, tmp_path):
    """Tape ends after MEND, with TEND missing — strict mode must reject."""
    parser = ParserCls(ignore_missing_tpid=True)
    text = _build_minimal_endf_text(parser)
    truncated = _strip_trailing_record(text, 1)  # drop only TEND
    fp = tmp_path / "no_tend.endf"
    fp.write_bytes(truncated.encode("latin-1"))
    strict = ParserCls(ignore_missing_tpid=True, ignore_send_records=False)
    with pytest.raises(Exception):
        strict.parsefile(str(fp))


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
@pytest.mark.parametrize("drop_n", [1, 2])
def test_truncated_tape_passes_with_ignore_send_records(ParserCls, tmp_path, drop_n):
    """With `ignore_send_records=True` the same truncated tapes parse
    without raising — confirms the override path."""
    parser = ParserCls(ignore_missing_tpid=True)
    text = _build_minimal_endf_text(parser)
    truncated = _strip_trailing_record(text, drop_n)
    fp = tmp_path / f"truncated_{drop_n}.endf"
    fp.write_bytes(truncated.encode("latin-1"))
    lenient = ParserCls(ignore_missing_tpid=True, ignore_send_records=True)
    lenient.parsefile(str(fp))
