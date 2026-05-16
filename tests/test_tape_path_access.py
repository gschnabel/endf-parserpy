"""Path-addressed item access on EndfFile (design P1-P4).

Covers the polymorphic ``[]`` / ``[]=`` / ``del`` / ``in`` protocol, the
``check_edits`` modes and the frozen / live section views, including
EndfPath-string keys on a view.
"""

import pytest
from pathlib import Path

from endf_parserpy import EndfParserFactory, EndfFile, EndfMaterialPath
from endf_parserpy.tape import AmbiguousMaterialError, SectionRenderError


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


def _read_lines(path):
    with open(path) as fh:
        return [line.rstrip("\n") for line in fh]


def _canonical_tape(parser, paths):
    tpid = tend = None
    bodies = []
    for path in paths:
        single = parser.write(parser.parse(_read_lines(path), exclude=RAW_EXCLUDE))
        tpid, tend = single[0], single[-1]
        bodies.append(single[1:-1])
    return [tpid] + sum(bodies, []) + [tend]


def _open(tmp_path, parser, paths, *, check_edits="eager", name="tape.endf"):
    path = tmp_path / name
    path.write_text("\n".join(_canonical_tape(parser, paths)) + "\n")
    return EndfFile(path, parser=parser, check_edits=check_edits)


# --------------------------------------------------------------------------
# reading at every depth (P1)
# --------------------------------------------------------------------------


def test_read_every_depth_and_spelling(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU])

    # material depth
    material = endf_file["#0"]
    assert material.position == 0
    assert material.mat == endf_file[0].mat == 2925

    # section depth -- [], get and the MaterialView spelling agree
    section = endf_file["#0/3/2"]
    assert section == endf_file.get("#0/3/2")
    assert section == endf_file[0][3, 2]

    # field depth
    awr = endf_file["#0/3/2/AWR"]
    assert awr == endf_file["#0/3/2"]["AWR"] == endf_file[0][3, 2]["AWR"]

    # by MAT number rather than position
    assert endf_file["2925/3/2/AWR"] == awr


def test_negative_int_material_index(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU, ZN])
    assert endf_file[-1].mat == endf_file[1].mat


# --------------------------------------------------------------------------
# membership (P1 / design section 9)
# --------------------------------------------------------------------------


def test_contains(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU])
    assert "#0" in endf_file
    assert "#0/3/2" in endf_file
    assert "#0/3/2/AWR" in endf_file
    assert 0 in endf_file
    # cleanly absent
    assert "#0/3/999" not in endf_file
    assert "#0/3/2/nonexistent_field" not in endf_file
    assert 5 not in endf_file
    # an ill-posed path is not silently answered False
    with pytest.raises(ValueError):
        "bogus/3/2" in endf_file


def test_contains_ambiguous_propagates(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU, CU])
    with pytest.raises(AmbiguousMaterialError):
        "2925/3/2" in endf_file


# --------------------------------------------------------------------------
# the error surface (design section 11)
# --------------------------------------------------------------------------


def test_error_surface(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU, CU])

    with pytest.raises(TypeError):
        endf_file[1.5]
    with pytest.raises(ValueError):
        endf_file["bogus/3/2"]
    with pytest.raises(AmbiguousMaterialError):
        endf_file["2925/3/2"]
    with pytest.raises(KeyError):
        endf_file["9999/3/2"]
    with pytest.raises(IndexError):
        endf_file["#9/3/2"]
    with pytest.raises(KeyError):
        endf_file["#0/3/999"]
    with pytest.raises(KeyError):
        endf_file["#0/3/2/nonexistent_field"]
    with pytest.raises(ValueError):
        endf_file["#0"] = {1: {451: {}}}
    with pytest.raises(ValueError):
        endf_file[0] = {1: {451: {}}}
    # MF-level addressing is not supported
    with pytest.raises(ValueError):
        endf_file["#0/3"]


# --------------------------------------------------------------------------
# writing -- section and field depth (P1 / P2)
# --------------------------------------------------------------------------


def test_section_assignment_roundtrip(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU, ZN])
    section = endf_file["#0/1/451"].detach()
    section["AWR"] = 99.5
    endf_file["#0/1/451"] = section
    assert endf_file["#0/1/451/AWR"] == 99.5

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert reopened["#0/1/451/AWR"] == 99.5
    # the other material is untouched
    assert reopened["#1/1/451/AWR"] == endf_file["#1/1/451/AWR"]


def test_field_assignment_roundtrip(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU])
    endf_file["#0/3/2/AWR"] = 88.0
    assert endf_file["#0/3/2/AWR"] == 88.0

    out = tmp_path / "out.endf"
    endf_file.export(out)
    assert EndfFile(out, parser=parser)["#0/3/2/AWR"] == 88.0


def test_delete_section_and_material(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU, ZN])
    del endf_file["#0/3/2"]
    assert "#0/3/2" not in endf_file
    del endf_file["#1"]
    assert len(endf_file) == 1


# --------------------------------------------------------------------------
# eager mode -- frozen views and immediate checking (P2 / P3)
# --------------------------------------------------------------------------


def test_eager_view_is_frozen(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="eager")
    section = endf_file["#0/3/2"]
    with pytest.raises(TypeError):
        section["AWR"] = 1.0
    # frozen recursively -- a nested container rejects mutation too
    with pytest.raises(TypeError):
        section["xstable"]["E"] = [1, 2, 3]
    with pytest.raises(TypeError):
        del section["AWR"]


def test_eager_detach_is_independent(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="eager")
    copy = endf_file["#0/3/2"].detach()
    assert isinstance(copy, dict)
    copy["AWR"] = -1.0
    # detached copy does not write through
    assert endf_file["#0/3/2/AWR"] != -1.0


def test_eager_malformed_section_raises_at_assignment(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="eager")
    with pytest.raises(SectionRenderError):
        endf_file["#0/3/2"] = {"this": "is garbage"}


def test_eager_field_delete_is_rejected(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="eager")
    with pytest.raises(ValueError):
        del endf_file["#0/3/2/AWR"]


# --------------------------------------------------------------------------
# deferred mode -- live write-through views (P2 / P3)
# --------------------------------------------------------------------------


def test_deferred_live_view_writes_through(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    section = endf_file["#0/3/2"]
    section["AWR"] = 70.0
    assert endf_file["#0/3/2/AWR"] == 70.0
    assert endf_file[0].is_modified


def test_deferred_nested_write_through(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    energies = list(endf_file["#0/3/2"]["xstable"]["E"])
    endf_file["#0/3/2"]["xstable"]["E"][0] = energies[0]
    assert endf_file[0].is_modified


def test_deferred_pure_read_keeps_tape_byte_exact(tmp_path, parser):
    multi = _canonical_tape(parser, [CU])
    path = tmp_path / "tape.endf"
    path.write_text("\n".join(multi) + "\n")
    endf_file = EndfFile(path, parser=parser, check_edits="deferred")
    # retrieving a live view and only *reading* must not mark anything dirty
    section = endf_file["#0/3/2"]
    _ = section["AWR"], section["xstable"]["E"][0]
    assert not endf_file[0].is_modified
    assert endf_file.to_string().splitlines() == multi


def test_deferred_two_views_share_state(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    view_a = endf_file["#0/3/2"]
    view_b = endf_file["#0/3/2"]
    view_a["AWR"] = 33.0
    assert view_b["AWR"] == 33.0


def test_deferred_field_delete_then_invalid_edits(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    del endf_file["#0/3/2/AWR"]  # accepted, leaves the section non-conformant
    report = endf_file.invalid_edits()
    assert len(report) == 1
    position, mf, mt, exc = report[0]
    assert (position, mf, mt) == (0, 3, 2)
    assert isinstance(exc, SectionRenderError)
    with pytest.raises(SectionRenderError):
        endf_file.to_string()


def test_deferred_detach_snapshot_does_not_write_through(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    snapshot = endf_file["#0/3/2"].detach()
    snapshot["AWR"] = -5.0
    assert endf_file["#0/3/2/AWR"] != -5.0
    assert not endf_file[0].is_modified


# --------------------------------------------------------------------------
# EndfPath-string keys on a view (P4)
# --------------------------------------------------------------------------


def test_path_key_read_on_view(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU])
    section = endf_file["#0/3/2"]
    # a multi-component key reads the same leaf as the chained spelling
    assert section["xstable/E"] == section["xstable"]["E"]
    # and the same leaf as the top-level path
    assert section["xstable/E"] == endf_file["#0/3/2/xstable/E"]


def test_path_key_write_on_live_view(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    section = endf_file["#0/3/2"]
    section["xstable/E"] = list(section["xstable/E"])
    assert endf_file[0].is_modified


def test_path_key_write_on_frozen_view_rejected(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="eager")
    section = endf_file["#0/3/2"]
    with pytest.raises(TypeError):
        section["xstable/E"] = [1, 2, 3]


# --------------------------------------------------------------------------
# raw (recipe-less) sections
# --------------------------------------------------------------------------


def test_field_assignment_into_raw_section_rejected(tmp_path, parser):
    endf_file = _open(tmp_path, parser, [CU], check_edits="deferred")
    # install a recipe-less raw section, then try to address a field of it
    endf_file["#0/3/2"] = ["a raw section line"]
    with pytest.raises(TypeError):
        endf_file["#0/3/2/AWR"] = 1.0


# --------------------------------------------------------------------------
# check_edits validation
# --------------------------------------------------------------------------


def test_invalid_check_edits_rejected(tmp_path, parser):
    multi = _canonical_tape(parser, [CU])
    path = tmp_path / "tape.endf"
    path.write_text("\n".join(multi) + "\n")
    with pytest.raises(ValueError, match="check_edits"):
        EndfFile(path, parser=parser, check_edits="sometimes")
