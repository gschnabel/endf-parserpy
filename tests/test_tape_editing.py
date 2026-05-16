import pickle
import pytest
from pathlib import Path

from endf_parserpy import EndfParserFactory, EndfFile
from endf_parserpy.tape import SectionRenderError, TapeStructureError


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


def _open(tmp_path, parser, paths, name="tape.endf"):
    path = tmp_path / name
    path.write_text("\n".join(_canonical_tape(parser, paths)) + "\n")
    return EndfFile(path, parser=parser), path


# --------------------------------------------------------------------------
# write-back without edits
# --------------------------------------------------------------------------


def test_unedited_export_is_byte_exact(tmp_path, parser):
    multi = _canonical_tape(parser, [CU, ZN])
    path = tmp_path / "tape.endf"
    path.write_text("\n".join(multi) + "\n")
    endf_file = EndfFile(path, parser=parser)
    assert endf_file.to_string().splitlines() == multi


def test_export_to_file(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    out = tmp_path / "out.endf"
    endf_file.export(out)
    assert EndfFile(out, parser=parser).materials()
    with pytest.raises(FileExistsError):
        endf_file.export(out)
    endf_file.export(out, overwrite=True)


def test_export_cleans_up_temp_file_on_failure(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    target = tmp_path / "adir"
    target.mkdir()  # a directory: the atomic replace onto it fails
    with pytest.raises(OSError):
        endf_file.export(target, overwrite=True)
    # a failed export must not leave its temporary file behind
    assert not (tmp_path / "adir.endfparserpy-tmp").exists()


def test_export_empty_tape_is_rejected(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    del endf_file[0]
    assert len(endf_file) == 0
    # a tape with no materials has no TPID and is not valid ENDF
    with pytest.raises(TapeStructureError, match="no materials"):
        endf_file.export(tmp_path / "out.endf")
    with pytest.raises(TapeStructureError, match="no materials"):
        endf_file.to_string()


def test_strip_send_only_strips_a_real_send():
    # regression: only a genuine SEND (MF>0, MT=0) is stripped; an
    # FEND/MEND/TEND record (also MT=0) must be left in place
    from endf_parserpy.tape.endf_file import _strip_send

    data = " " * 66 + "2925 3  2"  # a data record of MF=3/MT=2
    send = " " * 66 + "2925 3  0"  # SEND  (MF=3,  MT=0)
    fend = " " * 66 + "2925 0  0"  # FEND  (MF=0,  MT=0)
    assert _strip_send([data, send]) == [data]
    assert _strip_send([data, fend]) == [data, fend]
    assert _strip_send([data]) == [data]


def test_export_peak_memory_is_bounded(tmp_path, parser):
    # export streams material by material, so its peak memory is bounded
    # by a single material -- a 4x larger tape does not need 4x the heap
    import tracemalloc

    def peak_exporting(n_materials):
        path = tmp_path / f"tape{n_materials}.endf"
        path.write_text("\n".join(_canonical_tape(parser, [CU] * n_materials)) + "\n")
        endf_file = EndfFile(
            path, parser=parser, parsed_cache_bytes=1 << 20, raw_cache_bytes=1 << 20
        )
        out = tmp_path / f"out{n_materials}.endf"
        tracemalloc.start()
        try:
            endf_file.export(out)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert len(EndfFile(out, parser=parser)) == n_materials
        return peak

    small = peak_exporting(2)
    large = peak_exporting(8)
    assert large < small * 2


# --------------------------------------------------------------------------
# section editing
# --------------------------------------------------------------------------


def test_value_edit_roundtrip(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    assert not endf_file[0].is_modified

    section = dict(endf_file[0][1, 451])
    section["AWR"] = 123.5
    endf_file[0][1, 451] = section
    assert endf_file[0].is_modified

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert reopened[0][1, 451]["AWR"] == 123.5
    # the other material is untouched
    assert reopened[1][1, 451]["AWR"] == endf_file[1][1, 451]["AWR"]


def test_get_reflects_edits(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    section = dict(endf_file[0][1, 451])
    section["AWR"] = 77.0
    endf_file[0][1, 451] = section
    assert endf_file.get("#0/1/451/AWR") == 77.0


def test_delete_section(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    keys = endf_file[0].sections()
    victim = keys[-1]
    del endf_file[0][victim]
    assert victim not in endf_file[0]

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert victim not in reopened[0]
    assert len(reopened[0].sections()) == len(keys) - 1


def test_delete_then_readd_section(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    keys = set(endf_file[0].sections())
    victim = endf_file[0].sections()[-1]
    section = endf_file[0][victim]
    del endf_file[0][victim]
    assert victim not in endf_file[0]
    endf_file[0][victim] = section
    assert victim in endf_file[0]
    assert set(endf_file[0].sections()) == keys


def test_set_section_type_validation(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    with pytest.raises(TypeError):
        endf_file[0][1, 451] = 42


# --------------------------------------------------------------------------
# material editing
# --------------------------------------------------------------------------


def test_delete_material(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    assert len(endf_file) == 2
    cu_mat = endf_file[0].mat
    del endf_file[0]
    assert len(endf_file) == 1

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert len(reopened) == 1
    assert reopened[0].mat != cu_mat


def test_append_material(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    zn = parser.parse(_read_lines(ZN), exclude=RAW_EXCLUDE)
    view = endf_file.append_material(zn, mat=3025, za=30064)
    assert len(endf_file) == 2
    assert view.position == 1 and view.mat == 3025

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert len(reopened) == 2
    assert reopened[1].mat == 3025


def test_append_material_eager_rejects_malformed_section(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    # under check_edits="eager" a malformed appended section is rejected
    # right away, not deferred to export() time
    with pytest.raises(SectionRenderError):
        endf_file.append_material({1: {451: {"bogus": 1}}}, mat=9999)
    assert len(endf_file) == 1  # nothing was appended


def test_append_material_rejects_bad_section_type(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    with pytest.raises(TypeError):
        endf_file.append_material({3: {2: 42}}, mat=9999)
    assert len(endf_file) == 1


def test_delete_material_drops_cached_view(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    endf_file[0]  # materialise and cache the views
    endf_file[1]
    assert len(endf_file._material_views) == 2
    del endf_file[0]
    # the deleted material's view is dropped, not leaked
    assert len(endf_file._material_views) == 1


def test_reorder(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    mat0, mat1 = endf_file[0].mat, endf_file[1].mat
    endf_file.reorder([1, 0])
    assert (endf_file[0].mat, endf_file[1].mat) == (mat1, mat0)

    out = tmp_path / "out.endf"
    endf_file.export(out)
    reopened = EndfFile(out, parser=parser)
    assert (reopened[0].mat, reopened[1].mat) == (mat1, mat0)

    with pytest.raises(ValueError):
        endf_file.reorder([0, 0])


def test_export_to_same_path(tmp_path, parser):
    endf_file, path = _open(tmp_path, parser, [CU, ZN])
    del endf_file[1]
    endf_file.export(path, overwrite=True)
    reopened = EndfFile(path, parser=parser)
    assert len(reopened) == 1


def test_export_onto_source_invalidates(tmp_path, parser):
    from endf_parserpy.tape import StaleSourceError

    endf_file, path = _open(tmp_path, parser, [CU, ZN])
    endf_file.export(path, overwrite=True)
    # the in-memory index no longer matches the rewritten file
    with pytest.raises(StaleSourceError):
        len(endf_file)
    with pytest.raises(StaleSourceError):
        endf_file[0]
    with pytest.raises(StaleSourceError):
        endf_file.export(tmp_path / "elsewhere.endf")
    # the secondary lookups guard against the stale index too
    with pytest.raises(StaleSourceError):
        endf_file.by_za(29063)
    with pytest.raises(StaleSourceError):
        endf_file.find(za=29063)
    with pytest.raises(StaleSourceError):
        endf_file.query("1/451", value=0.0)
    assert "invalidated" in repr(endf_file)


def test_secondary_index_dropped_on_structural_edit(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    endf_file.build_index("1/451/AWR", name="by_awr")
    assert "by_awr" in endf_file.secondary_indexes
    del endf_file[0]
    # a position-keyed index would be wrong after a structural edit, so
    # it is dropped rather than left stale
    assert endf_file.secondary_indexes == {}


def test_save_to_other_path_keeps_object_valid(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    endf_file.export(tmp_path / "copy.endf")
    # saving elsewhere is a plain export and leaves the object usable
    assert len(endf_file) == 1
    endf_file.to_string()  # to_string() never invalidates either
    assert len(endf_file) == 1


# --------------------------------------------------------------------------
# view identity through structural edits
# --------------------------------------------------------------------------


def test_view_survives_reorder(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    view = endf_file[0]
    assert view.position == 0
    endf_file.reorder([1, 0])
    # the view is bound to the material, which moved to position 1
    assert view.position == 1
    assert view.mat == endf_file[1].mat


def test_deleted_material_view_is_invalid(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU, ZN])
    view = endf_file[1]
    del endf_file[1]
    with pytest.raises(RuntimeError):
        view.position


# --------------------------------------------------------------------------
# pickling preserves edits
# --------------------------------------------------------------------------


def test_pickle_preserves_edits(tmp_path, parser):
    endf_file, _ = _open(tmp_path, parser, [CU])
    section = dict(endf_file[0][1, 451])
    section["AWR"] = 55.0
    endf_file[0][1, 451] = section

    restored = pickle.loads(pickle.dumps(endf_file))
    assert restored[0].is_modified
    assert restored[0][1, 451]["AWR"] == 55.0
