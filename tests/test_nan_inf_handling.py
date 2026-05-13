############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/13
# Last modified:   2026/05/13
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Tests for the `accept_nan_inf` parsing flag and round-trip handling
of non-finite float values (NaN, +/-inf) in both the C++ and pure-Python
backends.
"""

import math
import pytest
from endf_parserpy import EndfParserCpp, EndfParserPy, EndfDict


PARSER_CLASSES = [EndfParserCpp, EndfParserPy]


def _build_mf3_dict_with_non_finites(non_finite_value):
    """Build an in-memory ENDF dict containing one MF=3/MT=2 section whose
    cross-section table includes the supplied non-finite value (NaN / +inf
    / -inf) at one grid point.
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
    sec["xstable/E"] = [1.0, 2.0, 3.0, 4.0, 5.0]
    sec["xstable/xs"] = [10.0, 20.0, non_finite_value, 40.0, 50.0]
    sec["xstable/NBT"] = [len(sec["xstable/E"])]
    sec["xstable/INT"] = [2]
    return d.unwrap()


def _xs_values(parsed_dict):
    xs = parsed_dict[3][2]["xstable"]["xs"]
    return list(xs.values()) if isinstance(xs, dict) else list(xs)


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_accept_nan_inf_default_roundtrips_nan(ParserCls):
    """With the default `accept_nan_inf=True`, a NaN value survives a
    write -> parse round-trip on both backends."""
    parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(float("nan"))
    text = parser.write(src)
    parsed = parser.parse(text)
    xs = _xs_values(parsed)
    assert len(xs) == 5
    assert xs[0] == 10.0 and xs[1] == 20.0 and xs[3] == 40.0 and xs[4] == 50.0
    assert math.isnan(xs[2])


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_accept_nan_inf_default_roundtrips_inf(ParserCls, value):
    """+inf and -inf survive a write -> parse round-trip on both backends."""
    parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(value)
    text = parser.write(src)
    parsed = parser.parse(text)
    xs = _xs_values(parsed)
    assert math.isinf(xs[2])
    assert (xs[2] > 0) == (value > 0)


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_accept_nan_inf_false_rejects_nan(ParserCls):
    """With `accept_nan_inf=False`, parsing a tape containing a NaN raises."""
    write_parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(float("nan"))
    text = write_parser.write(src)
    strict_parser = ParserCls(ignore_missing_tpid=True, accept_nan_inf=False)
    with pytest.raises(Exception):
        strict_parser.parse(text)


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_accept_nan_inf_false_rejects_inf(ParserCls, value):
    """With `accept_nan_inf=False`, parsing a tape containing +/-inf raises."""
    write_parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(value)
    text = write_parser.write(src)
    strict_parser = ParserCls(ignore_missing_tpid=True, accept_nan_inf=False)
    with pytest.raises(Exception):
        strict_parser.parse(text)


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
def test_writer_emits_nan_token_in_field(ParserCls):
    """The writer renders NaN as the textual token "NaN", right-aligned in the
    11-character field, so the line round-trips through any ENDF reader."""
    parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(float("nan"))
    text = parser.write(src)
    if isinstance(text, list):
        text = "\n".join(text)
    # Find an MF=3/MT=2 line containing the textual token; the third xs grid
    # point is the NaN, packed as the second pair on its 6-column row.
    matched = [
        line
        for line in text.splitlines()
        if line[70:72].strip() == "3" and line[72:75].strip() == "2" and "NaN" in line
    ]
    assert matched, "expected at least one MF=3/MT=2 line with the 'NaN' token"
    assert (
        "        NaN" in matched[0]
    ), f"expected NaN to be right-aligned in 11-char field, got: {matched[0]!r}"


@pytest.mark.parametrize("ParserCls", PARSER_CLASSES)
@pytest.mark.parametrize(
    "value,token", [(float("inf"), "Inf"), (float("-inf"), "-Inf")]
)
def test_writer_emits_inf_tokens_in_field(ParserCls, value, token):
    """The writer renders +/-inf as the textual tokens "Inf" / "-Inf",
    right-aligned in the 11-character field."""
    parser = ParserCls(ignore_missing_tpid=True)
    src = _build_mf3_dict_with_non_finites(value)
    text = parser.write(src)
    if isinstance(text, list):
        text = "\n".join(text)
    matched = [
        line
        for line in text.splitlines()
        if line[70:72].strip() == "3" and line[72:75].strip() == "2" and token in line
    ]
    assert matched, f"expected at least one MF=3/MT=2 line with the {token!r} token"
    assert (
        token.rjust(11) in matched[0]
    ), f"expected {token!r} to be right-aligned in 11-char field, got: {matched[0]!r}"
