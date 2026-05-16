import pytest
from pathlib import Path

from endf_parserpy import (
    EndfParserFactory,
    parse_tape,
    parse_tape_file,
    iter_parse_tape,
    write_tape,
    write_tape_file,
    FailedMaterial,
)
from endf_parserpy.tape import split_materials, TapeStructureError
from endf_parserpy.tape.splitter import TEND_LINE, _control_numbers


TESTDATA = Path(__file__).parent / "testdata"
# excluding every real MF section makes the parser keep all sections as
# raw text, which gives a byte-exact read/write round trip
RAW_EXCLUDE = tuple(range(1, 100))


@pytest.fixture(params=["python", "cpp"])
def parser(request):
    try:
        return EndfParserFactory.create(select=request.param)
    except Exception:
        pytest.skip(f"{request.param} backend unavailable")


def _read_lines(path):
    with open(path) as fh:
        return [line.rstrip("\n") for line in fh]


def _canonical_single(parser, path):
    """Return a single-material tape in canonical (re-written) form."""
    parsed = parser.parse(_read_lines(path), exclude=RAW_EXCLUDE)
    return parser.write(parsed)


def _make_multi(single, n=2):
    """Build an n-material tape by repeating one material's body."""
    tpid, tend = single[0], single[-1]
    body = single[1:-1]
    return [tpid] + body * n + [tend], tpid, body, tend


def _text(lines):
    """Join tape lines into the single-string form parse_tape expects."""
    return "\n".join(lines)


# --------------------------------------------------------------------------
# splitter: purely lexical, no parser needed
# --------------------------------------------------------------------------


def _fake_tape(n_materials):
    tpid = "test tape".ljust(66) + "   1 0  0"
    rec = " " * 66 + "1234 1451"
    send = " " * 66 + "1234 1  0"
    fend = " " * 66 + "1234 0  0"
    mend = " " * 66 + "   0 0  0"
    tend = " " * 66 + "  -1 0  0"
    material = [rec, send, fend, mend]
    return [tpid] + material * n_materials + [tend]


def test_split_materials_basic():
    chunks = list(split_materials(_fake_tape(3)))
    assert len(chunks) == 3
    for chunk in chunks:
        _, mf, mt = _control_numbers(chunk[0])
        assert (mf, mt) == (0, 0)  # starts with a TPID
        assert _control_numbers(chunk[-1])[0] == -1  # ends with a TEND
        assert chunk[-1] == TEND_LINE


def test_split_materials_skips_blank_lines():
    tape = _fake_tape(2)
    tape = [tape[0], "", ""] + tape[1:5] + [""] + tape[5:]
    chunks = list(split_materials(tape))
    assert len(chunks) == 2
    assert all(line.strip() != "" for chunk in chunks for line in chunk)


def test_split_materials_empty_input():
    with pytest.raises(TapeStructureError, match="does not contain any records"):
        list(split_materials([]))


def test_split_materials_missing_tpid():
    not_a_tpid = " " * 66 + "1234 3  1"  # MF=3, MT=1
    with pytest.raises(TapeStructureError, match="tape head"):
        list(split_materials([not_a_tpid]))


def test_split_materials_dangling_material():
    tpid = " " * 66 + "   1 0  0"
    record = " " * 66 + "1234 3  1"
    with pytest.raises(TapeStructureError, match="ends in the middle"):
        list(split_materials([tpid, record]))


# --------------------------------------------------------------------------
# parse_tape / write_tape against a real material
# --------------------------------------------------------------------------


def test_verbatim_roundtrip(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, tpid, body, tend = _make_multi(single, n=2)

    materials = parse_tape(_text(multi), parser=parser, exclude=RAW_EXCLUDE)
    assert len(materials) == 2

    out = write_tape(materials, parser=parser)
    assert out.splitlines() == multi


def test_parse_tape_matches_individual(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, *_ = _make_multi(single, n=2)

    chunks = list(split_materials(multi))
    materials = parse_tape(_text(multi), parser=parser, exclude=RAW_EXCLUDE)
    assert len(materials) == len(chunks) == 2
    for chunk, material in zip(chunks, materials):
        assert material == parser.parse(chunk, exclude=RAW_EXCLUDE)


def test_full_parse_yields_material_dicts(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, *_ = _make_multi(single, n=3)

    materials = parse_tape(_text(multi), parser=parser)
    assert len(materials) == 3
    for material in materials:
        assert not isinstance(material, FailedMaterial)
        # every ENDF material carries a descriptive MF1/MT451 section
        assert 1 in material and 451 in material[1]


def test_iter_parse_tape_matches_parse_tape(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, *_ = _make_multi(single, n=2)

    streamed = list(iter_parse_tape(_text(multi), parser=parser, exclude=RAW_EXCLUDE))
    eager = parse_tape(_text(multi), parser=parser, exclude=RAW_EXCLUDE)
    assert streamed == eager


def test_write_tape_file_roundtrip(parser, tmp_path):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, *_ = _make_multi(single, n=2)
    materials = parse_tape(_text(multi), parser=parser, exclude=RAW_EXCLUDE)

    out_file = tmp_path / "tape.endf"
    write_tape_file(materials, out_file, parser=parser)
    assert out_file.exists()

    with pytest.raises(FileExistsError):
        write_tape_file(materials, out_file, parser=parser)
    write_tape_file(materials, out_file, parser=parser, overwrite=True)

    reparsed = parse_tape_file(out_file, parser=parser, exclude=RAW_EXCLUDE)
    assert reparsed == materials


# --------------------------------------------------------------------------
# on_error policy
# --------------------------------------------------------------------------


def _corrupt_first_record(body):
    corrupted = list(body)
    for i, line in enumerate(corrupted):
        mat, mf, mt = _control_numbers(line)
        if mat > 0 and mf > 0 and mt > 0:
            # garble the six numeric fields, keep the control columns
            corrupted[i] = "X" * 66 + line[66:]
            return corrupted
    raise AssertionError("no regular record found to corrupt")


def test_on_error_mark(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    tpid, tend = single[0], single[-1]
    body = single[1:-1]
    bad_body = _corrupt_first_record(body)
    multi = [tpid] + body + bad_body + [tend]

    materials = parse_tape(_text(multi), parser=parser, on_error="mark")
    assert len(materials) == 2
    assert not isinstance(materials[0], FailedMaterial)
    assert isinstance(materials[1], FailedMaterial)
    assert materials[1].exception is not None
    assert materials[1].mat is not None


def test_on_error_raise(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    tpid, tend = single[0], single[-1]
    body = single[1:-1]
    multi = [tpid] + body + _corrupt_first_record(body) + [tend]

    with pytest.raises(Exception):
        parse_tape(_text(multi), parser=parser, on_error="raise")


def test_on_error_invalid_value(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    multi, *_ = _make_multi(single, n=2)
    with pytest.raises(ValueError, match="on_error"):
        parse_tape(_text(multi), parser=parser, on_error="bogus")


def test_failed_material_roundtrips_verbatim(parser):
    single = _canonical_single(parser, TESTDATA / "n_2925_29-Cu-63.endf")
    tpid, tend = single[0], single[-1]
    body = single[1:-1]
    bad_body = _corrupt_first_record(body)
    multi = [tpid] + body + bad_body + [tend]

    # full parse, so the corrupted material genuinely fails to parse
    materials = parse_tape(_text(multi), parser=parser, on_error="mark")
    failed = materials[1]
    assert isinstance(failed, FailedMaterial)

    # a FailedMaterial is written back verbatim from its stored lines
    assert write_tape([failed], parser=parser).splitlines() == failed.raw_lines
