"""Interop between the tape interface and the ordinary parser API.

These exercise the subpackage boundary: data read or written through the
multi-material tape interface (:class:`EndfFile`, :func:`write_tape`,
:func:`parse_tape`) must agree with data read or written through the
ordinary single-material ``EndfParserCpp`` / ``EndfParserPy`` API.
"""

import pytest
from pathlib import Path

from endf_parserpy import (
    EndfParserFactory,
    EndfFile,
    parse_tape_file,
    iter_parse_tape_file,
    write_tape,
    write_tape_file,
)


TESTDATA = Path(__file__).parent / "testdata"
CU = TESTDATA / "n_2925_29-Cu-63.endf"  # MAT 2925
ZN = TESTDATA / "n_3025_30-Zn-64.endf"  # MAT 3025


@pytest.fixture(params=["python", "cpp"])
def parser(request):
    try:
        return EndfParserFactory.create(select=request.param)
    except Exception:
        pytest.skip(f"{request.param} backend unavailable")


def _backends():
    out = {}
    for name in ("python", "cpp"):
        try:
            out[name] = EndfParserFactory.create(select=name)
        except Exception:
            pass
    return out


def _read_lines(path):
    with open(path) as fh:
        return [ln.rstrip("\n") for ln in fh]


def _section_keys(material):
    """The (MF, MT) keys of an ordinary parsed material, MF=0 aside."""
    return sorted((mf, mt) for mf in material if mf != 0 for mt in material[mf])


# --------------------------------------------------------------------------
# reading: EndfFile vs the ordinary parser
# --------------------------------------------------------------------------


def test_endf_file_section_equals_ordinary_parsefile(parser):
    # a section read through EndfFile equals the same section read with
    # the ordinary single-material parser, section for section
    ordinary = parser.parsefile(str(CU))
    endf_file = EndfFile(CU, parser=parser)
    assert endf_file[0].sections() == _section_keys(ordinary)
    for mf, mt in endf_file[0].sections():
        assert endf_file[0][mf, mt] == ordinary[mf][mt]


def test_iter_parse_tape_file_matches_endf_file(parser, tmp_path):
    # the streaming tape reader and the indexed EndfFile see the same
    # materials in the same order
    tape = tmp_path / "tape.endf"
    write_tape_file(
        [_read_lines(CU), _read_lines(ZN)], tape, parser=parser, overwrite=True
    )
    streamed = list(iter_parse_tape_file(tape, parser=parser))
    endf_file = EndfFile(tape, parser=parser)
    assert len(streamed) == len(endf_file) == 2
    for i, material in enumerate(streamed):
        for mf, mt in endf_file[i].sections():
            assert endf_file[i][mf, mt] == material[mf][mt]


# --------------------------------------------------------------------------
# ordinary-parsed data flowing into the tape interface
# --------------------------------------------------------------------------


def test_ordinary_parsed_materials_assembled_into_tape(parser, tmp_path):
    # materials parsed with the ordinary API, assembled into a tape with
    # write_tape and read back through EndfFile, survive unchanged
    cu = parser.parsefile(str(CU))
    zn = parser.parsefile(str(ZN))
    tape = tmp_path / "tape.endf"
    write_tape_file([cu, zn], tape, parser=parser, overwrite=True)
    endf_file = EndfFile(tape, parser=parser)
    assert len(endf_file) == 2
    for view, original in zip(endf_file, (cu, zn)):
        assert view.sections() == _section_keys(original)
        for mf, mt in view.sections():
            assert view[mf, mt] == original[mf][mt]


def test_tape_assembled_one_backend_read_by_the_other():
    # a tape assembled with one backend must read identically with the
    # other -- the on-disk ENDF text is the contract, not the engine
    backends = _backends()
    if len(backends) < 2:
        pytest.skip("both backends required")
    cpp, py = backends["cpp"], backends["python"]
    tape = write_tape([_read_lines(CU), _read_lines(ZN)], parser=cpp)
    lines = tape.splitlines()
    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".endf")
    os.close(fd)
    try:
        with open(path, "w") as fh:
            fh.write(tape)
        ef_cpp = EndfFile(path, parser=cpp)
        ef_py = EndfFile(path, parser=py)
        assert len(ef_cpp) == len(ef_py) == 2
        for i in range(2):
            assert ef_cpp[i].sections() == ef_py[i].sections()
            for mf, mt in ef_cpp[i].sections():
                assert ef_cpp[i][mf, mt] == ef_py[i][mf, mt]
    finally:
        os.remove(path)
    assert lines  # sanity


# --------------------------------------------------------------------------
# tape-interface output flowing back into the ordinary reader
# --------------------------------------------------------------------------


def test_endf_file_export_reread_by_ordinary_parse_tape(parser, tmp_path):
    # a tape written by EndfFile.export is readable by the ordinary
    # multi-material reader parse_tape_file, material for material
    src = tmp_path / "src.endf"
    write_tape_file(
        [_read_lines(CU), _read_lines(ZN)], src, parser=parser, overwrite=True
    )
    endf_file = EndfFile(src, parser=parser)
    out = tmp_path / "out.endf"
    endf_file.export(out)
    materials = parse_tape_file(out, parser=parser)
    assert len(materials) == 2
    for view, material in zip(endf_file, materials):
        for mf, mt in view.sections():
            assert view[mf, mt] == material[mf][mt]


def test_edit_via_endf_file_is_visible_to_ordinary_parser(parser, tmp_path):
    # an edit made through the tape interface is seen by the ordinary
    # parser when it re-reads the exported tape
    src = tmp_path / "src.endf"
    write_tape_file(
        [_read_lines(CU), _read_lines(ZN)], src, parser=parser, overwrite=True
    )
    endf_file = EndfFile(src, parser=parser)
    section = dict(endf_file[0][1, 451])
    section["AWR"] = 61.25
    endf_file[0][1, 451] = section
    out = tmp_path / "out.endf"
    endf_file.export(out)
    materials = parse_tape_file(out, parser=parser)
    assert materials[0][1][451]["AWR"] == 61.25
    # the untouched material is unchanged
    zn_ordinary = parser.parsefile(str(ZN))
    assert materials[1][1][451]["AWR"] == zn_ordinary[1][451]["AWR"]


# --------------------------------------------------------------------------
# MaterialView.to_tape_dict as a single-material tape for the ordinary API
# --------------------------------------------------------------------------


def test_to_tape_dict_is_a_writable_single_material_tape(parser, tmp_path):
    # to_tape_dict() carries the MF=0 tape head, so unlike per-section
    # access it forms a complete tape the ordinary writer accepts and
    # the ordinary parser round-trips
    tape = tmp_path / "tape.endf"
    write_tape_file(
        [_read_lines(CU), _read_lines(ZN)], tape, parser=parser, overwrite=True
    )
    endf_file = EndfFile(tape, parser=parser)
    for view in endf_file:
        tape_dict = view.to_tape_dict()
        assert 0 in tape_dict and 0 in tape_dict[0]  # MF=0/MT=0 tape head
        reparsed = parser.parse(parser.write(tape_dict))
        for mf, mt in view.sections():
            assert view[mf, mt] == reparsed[mf][mt]


def test_to_tape_dict_reflects_an_edit(parser, tmp_path):
    # an edit made through the view shows up in its to_tape_dict output
    tape = tmp_path / "tape.endf"
    write_tape_file(
        [_read_lines(CU), _read_lines(ZN)], tape, parser=parser, overwrite=True
    )
    endf_file = EndfFile(tape, parser=parser)
    section = dict(endf_file[0][1, 451])
    section["AWR"] = 61.25
    endf_file[0][1, 451] = section
    reparsed = parser.parse(parser.write(endf_file[0].to_tape_dict()))
    assert reparsed[1][451]["AWR"] == 61.25
