import gc
import pickle
import time
import pytest
from pathlib import Path

from endf_parserpy import EndfParserFactory, EndfFile
from endf_parserpy.tape import (
    split_materials,
    MaterialView,
    AmbiguousMaterialError,
    SectionParseError,
    StaleSourceError,
    TapeStructureError,
)
from endf_parserpy.tape.records import _control_numbers, TEND_LINE, DEFAULT_TPID_LINE


TESTDATA = Path(__file__).parent / "testdata"
ENDF_FILE = TESTDATA / "n_2925_29-Cu-63.endf"
RAW_EXCLUDE = tuple(range(1, 100))


@pytest.fixture(params=["python", "cpp"])
def parser(request):
    try:
        return EndfParserFactory.create(select=request.param)
    except Exception:
        pytest.skip(f"{request.param} backend unavailable")


@pytest.fixture(scope="module")
def multi_lines():
    base = EndfParserFactory.create(select="python")
    with open(ENDF_FILE) as fh:
        raw = [line.rstrip("\n") for line in fh]
    single = base.write(base.parse(raw, exclude=RAW_EXCLUDE))
    tpid, tend = single[0], single[-1]
    body = single[1:-1]
    return [tpid] + body * 3 + [tend]


@pytest.fixture
def tape_file(multi_lines, tmp_path):
    path = tmp_path / "tape.endf"
    path.write_text("\n".join(multi_lines) + "\n")
    return path


def _corrupt_tape(multi_lines, tmp_path):
    """Write a tape whose first material has a corrupt MF1/MT451 section."""
    lines = list(multi_lines)
    for i, line in enumerate(lines[1:], start=1):
        mat, mf, mt = _control_numbers(line)
        if mat > 0 and mf > 0 and mt > 0:
            lines[i] = "X" * 66 + line[66:]  # garble the data fields
            break
    path = tmp_path / "corrupt.endf"
    path.write_text("\n".join(lines) + "\n")
    return path


# --------------------------------------------------------------------------
# opening and the mapping protocol
# --------------------------------------------------------------------------


def test_open_and_iterate(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    assert len(endf_file) == 3
    views = list(endf_file)
    assert [v.position for v in views] == [0, 1, 2]
    assert all(isinstance(v, MaterialView) for v in views)
    assert endf_file[0] is endf_file[0]  # views are cached
    assert endf_file[-1].position == 2


def test_section_access_matches_parser(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    chunk = list(split_materials(tape_file_lines(tape_file)))[0]
    expected = parser.parse(chunk)[1][451]
    section = endf_file[0][1, 451]
    assert dict(section) == dict(expected)


def tape_file_lines(path):
    with open(path) as fh:
        return [line.rstrip("\n") for line in fh]


def test_material_view_protocol(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    material = endf_file[0]
    assert (1, 451) in material
    assert (99, 99) not in material
    assert len(material) == len(material.sections())
    assert set(material) == set(material.sections())
    assert material.za == 29063


def test_missing_section_raises_keyerror(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    with pytest.raises(KeyError, match="no MF=99/MT=99"):
        endf_file[0][99, 99]


# --------------------------------------------------------------------------
# laziness and the cache
# --------------------------------------------------------------------------


def test_lazy_nothing_parsed_until_access(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    assert endf_file.cache_nbytes == (0, 0)
    endf_file[0][1, 451]
    raw_bytes, parsed_bytes = endf_file.cache_nbytes
    assert raw_bytes > 0 and parsed_bytes > 0


def test_cache_eviction_under_tight_budget(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser, parsed_cache_bytes=1)
    for material in endf_file:
        for key in material.sections():
            material[key]
    # with a 1-byte budget the strong cache keeps only a single section
    assert len(endf_file._section_cache) == 1


def test_weakref_preserves_identity(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser, parsed_cache_bytes=1)
    held = endf_file[0][1, 451]
    # access every other section to force eviction from the strong cache
    for material in endf_file:
        for key in material.sections():
            material[key]
    # a re-access yields a fresh section view, but the canonical parsed
    # section it wraps is gone from the strong cache yet still alive, so
    # it is returned again with its identity intact
    assert endf_file[0][1, 451]._target is held._target


def test_section_cache_keeps_no_bookkeeping_beyond_strong_tier():
    # regression: the parsed-section cache must not retain per-entry
    # bookkeeping for evicted sections -- its only growing structure is
    # the strong tier, which the byte budget bounds
    from endf_parserpy.tape.cache import _SectionCache, _Section

    cache = _SectionCache(max_bytes=100)
    for i in range(1000):
        cache.put((i, 3, 2), _Section({"value": i}), weight=40)
    assert cache.nbytes <= cache.max_bytes
    assert len(cache._strong) <= 3  # only ~two 40-byte entries fit the budget


def test_unload_clears_cache(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    endf_file[0][1, 451]
    endf_file[1][1, 451]
    assert endf_file.cache_nbytes != (0, 0)
    endf_file.unload(position=0)
    endf_file.unload()
    assert endf_file.cache_nbytes == (0, 0)


def test_context_manager_unloads(tape_file, parser):
    with EndfFile(tape_file, parser=parser) as endf_file:
        endf_file[0][1, 451]
        assert endf_file.cache_nbytes != (0, 0)
    assert endf_file.cache_nbytes == (0, 0)


# --------------------------------------------------------------------------
# preload modes
# --------------------------------------------------------------------------


def test_mode_load_raw(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser, mode="load_raw")
    raw_bytes, parsed_bytes = endf_file.cache_nbytes
    assert raw_bytes > 0
    assert parsed_bytes == 0


def test_mode_parse_all(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser, mode="parse_all")
    assert endf_file.cache_nbytes[1] > 0


def test_open_a_valid_empty_tape(tmp_path, parser):
    path = tmp_path / "empty.endf"
    path.write_text(DEFAULT_TPID_LINE + "\n" + TEND_LINE + "\n")
    endf_file = EndfFile(path, parser=parser)
    assert len(endf_file) == 0


def test_tape_starting_with_tend_is_rejected(tmp_path, parser):
    # a TEND-only file has no TPID; the indexer must reject it rather
    # than mistake the TEND record for the tape head
    path = tmp_path / "tend_only.endf"
    path.write_text(TEND_LINE + "\n")
    with pytest.raises(TapeStructureError, match="MAT=-1"):
        EndfFile(path, parser=parser)


def test_invalid_mode_and_on_error(tape_file, parser):
    with pytest.raises(ValueError, match="mode"):
        EndfFile(tape_file, parser=parser, mode="bogus")
    with pytest.raises(ValueError, match="on_error"):
        EndfFile(tape_file, parser=parser, on_error="bogus")


# --------------------------------------------------------------------------
# secondary lookups
# --------------------------------------------------------------------------


def test_by_mat_ambiguous(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    mat = endf_file[0].mat
    with pytest.raises(AmbiguousMaterialError, match="3 materials"):
        endf_file.by_mat(mat)
    chosen = endf_file.by_mat(mat, occurrence=1)
    assert chosen.position == 1
    with pytest.raises(KeyError):
        endf_file.by_mat(999999)


def test_by_za_and_find(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    assert [v.position for v in endf_file.by_za(29063)] == [0, 1, 2]
    assert endf_file.by_za(1) == []
    assert [v.position for v in endf_file.find(za=29063)] == [0, 1, 2]


# --------------------------------------------------------------------------
# on_error policy
# --------------------------------------------------------------------------


def test_on_error_mark(multi_lines, tmp_path, parser):
    path = _corrupt_tape(multi_lines, tmp_path)
    endf_file = EndfFile(path, parser=parser, on_error="mark")
    # accessing the corrupt section raises SectionParseError -- the same
    # as on_error="raise" -- but with "mark" the failure is contained:
    with pytest.raises(SectionParseError, match="MF=1/MT=451"):
        endf_file[0][1, 451]
    # an intact material is unaffected ...
    assert endf_file[2][1, 451]["AWR"] is not None
    # ... and the corrupt material round-trips verbatim through export()
    out = tmp_path / "out.endf"
    endf_file.export(out)
    assert len(EndfFile(out, parser=parser)) == len(endf_file)


def test_on_error_raise(multi_lines, tmp_path, parser):
    path = _corrupt_tape(multi_lines, tmp_path)
    endf_file = EndfFile(path, parser=parser, on_error="raise")
    with pytest.raises(SectionParseError, match="MF=1/MT=451"):
        endf_file[0][1, 451]


def test_contains_false_for_unparsable_section_field(multi_lines, tmp_path, parser):
    path = _corrupt_tape(multi_lines, tmp_path)
    for mode in ("mark", "raise"):
        endf_file = EndfFile(path, parser=parser, on_error=mode)
        # the corrupt section is structurally present ...
        assert "#0/1/451" in endf_file
        # ... but a field within it is unreachable, so `in` answers
        # False rather than raising, in either on_error mode
        assert "#0/1/451/AWR" not in endf_file


# --------------------------------------------------------------------------
# verify_source
# --------------------------------------------------------------------------


def test_verify_source_detects_change(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser, verify_source=True)
    endf_file[0][1, 451]  # fine
    endf_file.unload()
    time.sleep(0.01)
    tape_file.write_text(tape_file.read_text() + "\n")
    with pytest.raises(StaleSourceError):
        endf_file[0][1, 451]


# --------------------------------------------------------------------------
# pickling
# --------------------------------------------------------------------------


def test_pickle_roundtrip(tape_file, parser):
    endf_file = EndfFile(tape_file, parser=parser)
    expected = dict(endf_file[0][1, 451])

    restored = pickle.loads(pickle.dumps(endf_file))
    assert len(restored) == 3
    assert restored.cache_nbytes == (0, 0)  # caches are not pickled
    assert dict(restored[0][1, 451]) == expected
