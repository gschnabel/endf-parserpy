import pytest
from pathlib import Path

from endf_parserpy import EndfParserFactory, EndfFile, EndfMaterialPath, TapeIndex
from endf_parserpy.tape import AmbiguousMaterialError, SectionParseError
from endf_parserpy.tape.splitter import _control_numbers


TESTDATA = Path(__file__).parent / "testdata"
CU = TESTDATA / "n_2925_29-Cu-63.endf"  # MAT 2925
ZN = TESTDATA / "n_3025_30-Zn-64.endf"  # MAT 3025
RAW_EXCLUDE = tuple(range(1, 100))


@pytest.fixture(params=["python", "cpp"])
def parser(request):
    try:
        return EndfParserFactory.create(select=request.param)
    except Exception:
        pytest.skip(f"{request.param} backend unavailable")


def _body(path):
    base = EndfParserFactory.create(select="python")
    with open(path) as fh:
        raw = [line.rstrip("\n") for line in fh]
    single = base.write(base.parse(raw, exclude=RAW_EXCLUDE))
    return single[0], single[1:-1], single[-1]


def _write_tape(tmp_path, paths):
    tpid = tend = None
    bodies = []
    for path in paths:
        tpid, body, tend = _body(path)
        bodies.append(body)
    lines = [tpid] + sum(bodies, []) + [tend]
    out = tmp_path / "tape.endf"
    out.write_text("\n".join(lines) + "\n")
    return out


def _corrupt_first_record(lines):
    out = list(lines)
    for i, line in enumerate(out[1:], start=1):
        mat, mf, mt = _control_numbers(line)
        if mat > 0 and mf > 0 and mt > 0:
            out[i] = "X" * 66 + line[66:]
            break
    return out


# --------------------------------------------------------------------------
# EndfMaterialPath parsing and resolution
# --------------------------------------------------------------------------


def test_material_path_parsing():
    p = EndfMaterialPath("9237#1/3/2/xstable")
    assert (p.mf, p.mt) == (3, 2)
    assert p.subpath is not None

    p2 = EndfMaterialPath("#0/1/451")
    assert (p2.mf, p2.mt) == (1, 451)
    assert p2.subpath is None

    p3 = EndfMaterialPath("2925")
    assert p3.mf is None and p3.mt is None

    assert EndfMaterialPath(p) == p  # copy constructor

    with pytest.raises(ValueError):
        EndfMaterialPath("")
    with pytest.raises(ValueError, match="material selector"):
        EndfMaterialPath("bogus/1/451")


def test_resolve_material(tmp_path):
    tape = _write_tape(tmp_path, [CU, CU, ZN])  # MAT 2925, 2925, 3025
    index = TapeIndex.from_file(tape)

    assert EndfMaterialPath("#1/1/451").resolve_material(index) == 1
    assert EndfMaterialPath("2925#1/1/451").resolve_material(index) == 1
    assert EndfMaterialPath("3025/1/451").resolve_material(index) == 2

    with pytest.raises(AmbiguousMaterialError):
        EndfMaterialPath("2925/1/451").resolve_material(index)
    with pytest.raises(IndexError):
        EndfMaterialPath("#9/1/451").resolve_material(index)
    with pytest.raises(KeyError):
        EndfMaterialPath("9999/1/451").resolve_material(index)


# --------------------------------------------------------------------------
# EndfFile.get
# --------------------------------------------------------------------------


def test_get_value_and_section(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)

    awr0 = endf_file[0][1, 451]["AWR"]
    assert endf_file.get("#0/1/451/AWR") == awr0
    assert endf_file.get(EndfMaterialPath("#0/1/451/AWR")) == awr0
    # an empty subpath addresses the whole section
    assert dict(endf_file.get("#1/1/451")) == dict(endf_file[1][1, 451])


def test_get_ambiguous(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, CU])
    endf_file = EndfFile(tape, parser=parser)
    with pytest.raises(AmbiguousMaterialError):
        endf_file.get("2925/1/451/AWR")
    assert endf_file.get("2925#1/1/451/AWR") == endf_file[1][1, 451]["AWR"]


def test_get_material_depth_returns_material_view(tmp_path, parser):
    # get() is relaxed: a material-depth path yields a MaterialView,
    # the exact synonym of endf_file[path].
    tape = _write_tape(tmp_path, [CU])
    endf_file = EndfFile(tape, parser=parser)
    material = endf_file.get("#0")
    assert material.position == 0
    assert material.mat == endf_file[0].mat
    assert endf_file.get("2925").mat == 2925


def test_get_failed_section_raises(tmp_path, parser):
    tpid, body, tend = _body(CU)
    lines = _corrupt_first_record([tpid] + body + [tend])
    tape = tmp_path / "corrupt.endf"
    tape.write_text("\n".join(lines) + "\n")
    endf_file = EndfFile(tape, parser=parser, on_error="mark")
    with pytest.raises(SectionParseError):
        endf_file.get("#0/1/451/AWR")


# --------------------------------------------------------------------------
# build_index
# --------------------------------------------------------------------------


def test_build_index(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)

    mapping = endf_file.build_index("1/451/AWR")
    assert len(mapping) == 2  # Cu and Zn have distinct AWR values
    assert sum(len(v) for v in mapping.values()) == 2
    assert mapping[endf_file[0][1, 451]["AWR"]] == [0]


def test_build_index_named(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)
    endf_file.build_index("1/451/AWR", name="awr")
    assert "awr" in endf_file.secondary_indexes
    assert endf_file.secondary_indexes["awr"] == endf_file.build_index("1/451/AWR")


def test_build_index_on_error(tmp_path, parser):
    tpid, body, tend = _body(CU)
    _, body2, _ = _body(ZN)
    lines = _corrupt_first_record([tpid] + body + body2 + [tend])
    tape = tmp_path / "corrupt.endf"
    tape.write_text("\n".join(lines) + "\n")

    marked = EndfFile(tape, parser=parser, on_error="mark")
    mapping = marked.build_index("1/451/AWR")
    # the corrupt material 0 is skipped; only material 1 is indexed
    assert sum(len(v) for v in mapping.values()) == 1

    raising = EndfFile(tape, parser=parser, on_error="raise")
    with pytest.raises(SectionParseError):
        raising.build_index("1/451/AWR")


# --------------------------------------------------------------------------
# query
# --------------------------------------------------------------------------


def test_query_by_value(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)
    awr0 = endf_file[0][1, 451]["AWR"]
    result = endf_file.query("1/451/AWR", awr0)
    assert [m.position for m in result] == [0]


def test_query_by_predicate(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)
    awr = [endf_file[i][1, 451]["AWR"] for i in (0, 1)]
    heaviest = max(awr)
    result = endf_file.query("1/451/AWR", predicate=lambda v: v == heaviest)
    assert len(result) == 1
    assert result[0].position == awr.index(heaviest)


def test_query_with_tolerance(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU, ZN])
    endf_file = EndfFile(tape, parser=parser)
    awr0 = endf_file[0][1, 451]["AWR"]
    assert endf_file.query("1/451/AWR", awr0 + 1e-6) == []
    near = endf_file.query("1/451/AWR", awr0 + 1e-6, tol=1e-3)
    assert [m.position for m in near] == [0]


def test_query_invalid_arguments(tmp_path, parser):
    tape = _write_tape(tmp_path, [CU])
    endf_file = EndfFile(tape, parser=parser)
    with pytest.raises(ValueError, match="exactly one"):
        endf_file.query("1/451/AWR")
    with pytest.raises(ValueError, match="exactly one"):
        endf_file.query("1/451/AWR", 1.0, predicate=lambda v: True)
    with pytest.raises(ValueError, match="MF/MT"):
        endf_file.query("1", 1.0)
