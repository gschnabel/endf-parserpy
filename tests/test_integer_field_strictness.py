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

"""Tests that both backends strictly reject float-shaped values placed
in ENDF integer fields. Regression coverage for issue #58 where the
C++ parser silently truncated values like "0.000000+0" via `std::atoi`,
while the Python parser correctly raised on `int("0.000000+0")`.
"""

import pytest
from endf_parserpy import EndfParserCpp, EndfParserPy


PARSER_CLASSES = [EndfParserCpp, EndfParserPy]


# A MF=32/MT=151 tape hand-crafted (mimicking the ChatGPT-generated file
# from issue #58) so that the LRU/LRF/NRO/NAPS integer slots on line 3
# contain `0.000000+0` style float literals instead of right-aligned ints.
MF32_WITH_FLOATS_IN_INT_FIELDS = (
    " 2.350439+2 0.000000+0          2          0          1          0 12532151    1\n"
    " 5.000000-1 0.000000+0          0          0          2          2 12532151    2\n"
    " 1.000000-4 0.000000+0 0.000000+0 0.000000+0 4.000000-6 0.000000+0 12532151    3\n"
    " 0.000000+0 0.000000+0 1.000000-4                                  12532151    4\n"
    " 4.000000-4 0.000000+0 0.000000+0 0.000000+0 2.500000-5 0.000000+0 12532151    5\n"
    " 0.000000+0 0.000000+0 1.000000-4                                  12532151    6\n"
    "                                                                   12532  0    0\n"
)


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_float_in_integer_field_rejected(ParserCls, tmp_path):
    """A tape that packs `0.000000+0` into integer-typed CONT slots must
    be rejected by both backends. Issue #58."""
    fp = tmp_path / "mf32_floats_in_int_fields.endf"
    fp.write_bytes(MF32_WITH_FLOATS_IN_INT_FIELDS.encode("latin-1"))
    parser = ParserCls(ignore_send_records=True, ignore_missing_tpid=True)
    with pytest.raises(Exception):
        parser.parsefile(str(fp))


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_blank_integer_field_treated_as_zero(ParserCls, tmp_path):
    """ENDF convention: an all-blank 11-character integer field reads as
    zero on both backends. Sanity check guarding the strict path."""
    # Build a minimal MF=3/MT=2 tape via the parser, then verify it
    # round-trips. The xstable head record contains blank-filled integer
    # slots (L1, L2 both 0), exercising the blank-as-zero path.
    from endf_parserpy import EndfDict

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
    parser = ParserCls(ignore_missing_tpid=True)
    text = parser.write(d.unwrap())
    if isinstance(text, list):
        text = "\n".join(text) + "\n"
    fp = tmp_path / "minimal.endf"
    fp.write_bytes(text.encode("latin-1"))
    parser.parsefile(str(fp))
