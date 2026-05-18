"""Tests for multi-material support in endf-cli.

Covers the shared cmd_utils helper layer and the per-subcommand
multi-material behaviour. Subcommand cases run endf-cli as a subprocess
against single- and multi-material fixtures.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from endf_parserpy import EndfParserCpp, parse_tape_file, write_tape_file
from endf_parserpy.cli.cmd_utils import (
    open_endf_file,
    resolve_material_path,
    format_material_table,
)

REPO = Path(__file__).resolve().parent.parent
TESTDATA = REPO / "tests" / "testdata"
CU = TESTDATA / "n_2925_29-Cu-63.endf"
ZN = TESTDATA / "n_3025_30-Zn-64.endf"


@pytest.fixture(scope="module")
def parser():
    return EndfParserCpp()


def run_cli(argv, cwd=None, stdin=None):
    """Run endf-cli as a subprocess against the in-repo source."""
    env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONHASHSEED": "0"}
    return subprocess.run(
        [sys.executable, "-m", "endf_parserpy.cli.cmd", *argv],
        cwd=cwd,
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def two_material_tape(tmp_path_factory, parser):
    """A 2-material tape: Cu-63 (MAT 2925) followed by Zn-64 (MAT 3025)."""
    cu = parse_tape_file(CU, parser=parser)[0]
    zn = parse_tape_file(ZN, parser=parser)[0]
    path = tmp_path_factory.mktemp("tape") / "tape.endf"
    write_tape_file([cu, zn], path, parser=parser, overwrite=True)
    return path


@pytest.fixture(scope="module")
def tape_with_bad_material(tmp_path_factory, two_material_tape):
    """The 2-material tape with a data field of the 2nd material (MAT 3025)
    corrupted, so that material #1 fails to parse while the structural
    index stays intact."""
    lines = Path(two_material_tape).read_text().splitlines(keepends=True)
    corrupted = False
    out = []
    for line in lines:
        if not corrupted and line[66:70] == "3025" and line[70:72] == " 3":
            line = "BADBADBAD!!" + line[11:]
            corrupted = True
        out.append(line)
    assert corrupted, "could not find an MF3 line of MAT 3025 to corrupt"
    path = tmp_path_factory.mktemp("badtape") / "bad.endf"
    path.write_text("".join(out))
    return path


# --- Phase 2: cmd_utils helper layer ---------------------------------------


def test_open_endf_file_single(parser):
    assert len(open_endf_file(CU, parser)) == 1


def test_open_endf_file_multi(two_material_tape, parser):
    assert len(open_endf_file(two_material_tape, parser)) == 2


def test_resolve_path_single_material_bare(parser):
    ef = open_endf_file(CU, parser)
    assert resolve_material_path(ef, "3/2/AWR") == "#0/3/2/AWR"
    assert resolve_material_path(ef, "") == "#0"


def test_resolve_path_hash_passthrough(parser):
    ef = open_endf_file(CU, parser)
    assert resolve_material_path(ef, "#0/3/2") == "#0/3/2"


def test_resolve_path_multi_material_bare_rejected(two_material_tape, parser, capsys):
    ef = open_endf_file(two_material_tape, parser)
    with pytest.raises(SystemExit) as exc:
        resolve_material_path(ef, "3/2/AWR")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "2 materials" in err
    assert "#0" in err and "#1" in err


def test_resolve_path_multi_material_hash_ok(two_material_tape, parser):
    ef = open_endf_file(two_material_tape, parser)
    assert resolve_material_path(ef, "#1/3/2/AWR") == "#1/3/2/AWR"


def test_format_material_table(two_material_tape, parser):
    table = format_material_table(open_endf_file(two_material_tape, parser))
    assert "#0" in table and "#1" in table
    assert "MAT=2925" in table and "MAT=3025" in table


# --- Phase 3: the list subcommand ------------------------------------------


def test_list_single_material():
    result = run_cli(["list", str(CU)])
    assert result.returncode == 0
    assert "1 material" in result.stdout
    assert "MAT=2925" in result.stdout


def test_list_multi_material(two_material_tape):
    result = run_cli(["list", str(two_material_tape)])
    assert result.returncode == 0
    assert "2 materials" in result.stdout
    assert "#0" in result.stdout and "#1" in result.stdout
    assert "MAT=2925" in result.stdout and "MAT=3025" in result.stdout


# --- Phase 4: the validate subcommand --------------------------------------


def test_validate_multi_material_ok(two_material_tape):
    result = run_cli(["validate", str(two_material_tape)])
    assert result.returncode == 0
    assert "ok - " in result.stdout
    assert "failed" not in result.stdout


def test_validate_multi_material_failure(tape_with_bad_material):
    result = run_cli(["validate", str(tape_with_bad_material)])
    assert result.returncode == 1
    assert "failed - " in result.stdout
    # the failure detail pinpoints the offending material
    assert "material #1" in result.stdout
    assert "MAT 3025" in result.stdout


# --- Phase 5: the explain subcommand ---------------------------------------

EXPLAIN_AWR = "ratio of the mass of the material to that of the neutron"


def test_explain_single_material_bare_path():
    """A selector-less path still works on a single-material file."""
    result = run_cli(["explain", "1/451/AWR", str(CU)])
    assert result.returncode == 0
    assert EXPLAIN_AWR in result.stdout


def test_explain_multi_material_with_selector(two_material_tape):
    """A #-prefixed path explains a variable of the selected material."""
    result = run_cli(["explain", "#1/1/451/AWR", str(two_material_tape)])
    assert result.returncode == 0
    assert EXPLAIN_AWR in result.stdout


def test_explain_multi_material_bare_path_rejected(two_material_tape):
    """On a multi-material tape a selector-less path is rejected."""
    result = run_cli(["explain", "1/451/AWR", str(two_material_tape)])
    assert result.returncode == 1
    assert "2 materials" in result.stderr
    assert "#0" in result.stderr and "#1" in result.stderr


# --- Phase 6: the match subcommand -----------------------------------------


def test_match_multi_material_all(two_material_tape):
    """A query satisfied by every material reports every material."""
    result = run_cli(["match", str(two_material_tape), "--query", "exists(/3/2)"])
    assert result.returncode == 0
    assert "material #0, MAT 2925" in result.stdout
    assert "material #1, MAT 3025" in result.stdout


def test_match_multi_material_selective(two_material_tape):
    """A query satisfied by only one material reports only that one."""
    result = run_cli(["match", str(two_material_tape), "--query", "/1/451/ZA == 30064"])
    assert result.returncode == 0
    assert "material #1, MAT 3025" in result.stdout
    assert "material #0" not in result.stdout


def test_match_parse_failure_reported_on_stderr(tape_with_bad_material):
    """A material that fails to parse is reported on stderr, not stdout."""
    result = run_cli(["match", str(tape_with_bad_material), "--query", "exists(/3/2)"])
    assert result.returncode == 1
    assert "parsing failed" in result.stderr
    assert "parsing failed" not in result.stdout


# --- Phase 7: the show subcommand ------------------------------------------


def test_show_single_material_bare_path():
    """A selector-less path still works on a single-material file."""
    result = run_cli(["show", "3/2/AWR", str(CU)])
    assert result.returncode == 0
    assert "62.389" in result.stdout


def test_show_multi_material_value(two_material_tape):
    """A #-prefixed path shows a field of the selected material."""
    result = run_cli(["show", "#1/3/2/AWR", str(two_material_tape)])
    assert result.returncode == 0
    assert "63.38" in result.stdout


def test_show_multi_material_section(two_material_tape):
    """A #-prefixed section path shows that material's section."""
    result = run_cli(["show", "#1/3/2", str(two_material_tape)])
    assert result.returncode == 0
    assert "/ZA:" in result.stdout and "30064" in result.stdout


def test_show_multi_material_material_depth(two_material_tape):
    """A material-depth path lists the material's sections."""
    result = run_cli(["show", "#0", str(two_material_tape)])
    assert result.returncode == 0
    assert "MAT=2925" in result.stdout
    assert "sections (MF/MT):" in result.stdout
    assert "1/451" in result.stdout


def test_show_multi_material_bare_path_rejected(two_material_tape):
    """On a multi-material tape a selector-less path is rejected."""
    result = run_cli(["show", "3/2", str(two_material_tape)])
    assert result.returncode == 1
    assert "2 materials" in result.stderr


def test_show_mf_depth_lists_mt_sections(two_material_tape):
    """An MF-depth path lists the MT numbers present in that MF file."""
    result = run_cli(["show", "#1/3", str(two_material_tape)])
    assert result.returncode == 0
    assert "MF=3 sections (MT):" in result.stdout
    assert " 1," in result.stdout and " 2" in result.stdout


def test_show_leading_and_trailing_slashes_accepted():
    """Surrounding slashes in a path are optional (e.g. '/3/2/')."""
    bare = run_cli(["show", "3/2/AWR", str(CU)])
    slashed = run_cli(["show", "/3/2/AWR/", str(CU)])
    assert slashed.returncode == 0
    assert slashed.stdout == bare.stdout


# --- Phase 8: the update-directory subcommand ------------------------------


def test_update_directory_multi_material(two_material_tape, parser, tmp_path):
    """update-directory rewrites the MF1/MT451 directory of every material."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["update-directory", "-n", str(work)])
    assert result.returncode == 0
    endf_file = open_endf_file(work, parser)
    assert len(endf_file) == 2
    for material in endf_file:
        mt451 = material[1, 451]
        listed = set(zip(mt451["MFx"].values(), mt451["MTx"].values()))
        assert listed == set(material.sections())


# --- Phase 9: the convert subcommand ---------------------------------------


def test_convert_single_material_json_is_object(tmp_path):
    """A single-material tape converts to a JSON object."""
    out = tmp_path / "cu.json"
    result = run_cli(["convert", str(CU), str(out), "--to", "json"])
    assert result.returncode == 0
    import json

    data = json.loads(out.read_text())
    assert isinstance(data, dict)


def test_convert_multi_material_json_is_array(two_material_tape, tmp_path):
    """A multi-material tape converts to a JSON array of materials."""
    out = tmp_path / "tape.json"
    result = run_cli(["convert", str(two_material_tape), str(out), "--to", "json"])
    assert result.returncode == 0
    import json

    data = json.loads(out.read_text())
    assert isinstance(data, list) and len(data) == 2


def test_convert_multi_material_roundtrip(two_material_tape, parser, tmp_path):
    """endf -> json -> endf preserves both materials of a tape."""
    js = tmp_path / "tape.json"
    rt = tmp_path / "roundtrip.endf"
    assert (
        run_cli(["convert", str(two_material_tape), str(js), "--to", "json"]).returncode
        == 0
    )
    assert run_cli(["convert", str(js), str(rt), "--to", "endf"]).returncode == 0
    materials = parse_tape_file(rt, parser=parser)
    assert [m[1][451]["MAT"] for m in materials] == [2925, 3025]


# --- Phase 10: the insert-text subcommand ----------------------------------

MARKER = "INSERTED MARKER LINE"


def _description(material):
    from endf_parserpy.utils.endf6_plumbing import get_description

    return get_description(material)


def test_insert_text_single_material(tmp_path):
    """A selector-less insert-text works on a single-material file."""
    work = tmp_path / "cu.endf"
    shutil.copy(CU, work)
    result = run_cli(["insert-text", "-n", str(work)], stdin=MARKER + "\n")
    assert result.returncode == 0
    assert MARKER in _description(parse_tape_file(work)[0])


def test_insert_text_multi_material_with_selector(two_material_tape, parser, tmp_path):
    """-m selects which material of a tape receives the text."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["insert-text", "-n", "-m", "#1", str(work)], stdin=MARKER + "\n")
    assert result.returncode == 0
    materials = parse_tape_file(work, parser=parser)
    assert MARKER not in _description(materials[0])
    assert MARKER in _description(materials[1])


def test_insert_text_multi_material_without_selector_rejected(
    two_material_tape, tmp_path
):
    """On a multi-material tape insert-text requires -m/--material."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["insert-text", "-n", str(work)], stdin=MARKER + "\n")
    assert result.returncode == 1
    assert "2 materials" in result.stderr
    assert "-m/--material" in result.stderr


# --- Phase 11: the compare subcommand --------------------------------------


@pytest.fixture(scope="module")
def modified_cu(tmp_path_factory, parser):
    """A copy of the Cu-63 file (same MAT 2925) with its AWR field bumped."""
    cu = parse_tape_file(CU, parser=parser)[0]
    cu[1][451]["AWR"] = cu[1][451]["AWR"] + 1.0
    path = tmp_path_factory.mktemp("modcu") / "cu_mod.endf"
    write_tape_file([cu], path, parser=parser, overwrite=True)
    return path


def test_compare_same_mat_equal():
    """Two identical single-material files compare equal."""
    result = run_cli(["compare", str(CU), str(CU)])
    assert result.returncode == 0
    assert result.stdout == ""


def test_compare_same_mat_diff(modified_cu):
    """Same-MAT files that differ produce a field diff and exit code 1."""
    result = run_cli(["compare", str(CU), str(modified_cu)])
    assert result.returncode == 1
    assert "AWR" in result.stdout


def test_compare_cross_mat_unpaired():
    """Single-material files with different MAT numbers are reported unpaired."""
    result = run_cli(["compare", str(CU), str(ZN)])
    assert result.returncode == 1
    assert "unpaired" in result.stdout
    assert "MAT 2925" in result.stdout and "MAT 3025" in result.stdout


def test_compare_multi_material_paired(two_material_tape):
    """A multi-material tape compared with itself pairs every material."""
    result = run_cli(["compare", str(two_material_tape), str(two_material_tape)])
    assert result.returncode == 0
    assert "MAT 2925" in result.stdout and "MAT 3025" in result.stdout
    assert "unpaired" not in result.stdout


def test_compare_multi_vs_single_partial(two_material_tape):
    """Comparing a 2-material tape with a 1-material file pairs the common
    MAT and reports the rest as unpaired."""
    result = run_cli(["compare", str(two_material_tape), str(CU)])
    assert result.returncode == 1
    assert "unpaired" in result.stdout
    assert "MAT 3025" in result.stdout


# --- Phase 12: the replace subcommand --------------------------------------


@pytest.fixture(scope="module")
def donor_tape(tmp_path_factory, parser):
    """A 2-material tape whose 2nd material (Zn-64) has a distinctive
    MF3/MT2 AWR value, so a replacement from it is observable."""
    cu = parse_tape_file(CU, parser=parser)[0]
    zn = parse_tape_file(ZN, parser=parser)[0]
    zn[3][2]["AWR"] = 999.0
    path = tmp_path_factory.mktemp("donor") / "donor.endf"
    write_tape_file([cu, zn], path, parser=parser, overwrite=True)
    return path


def test_replace_single_material_bare_path(modified_cu, parser, tmp_path):
    """A selector-less replace works between two single-material files."""
    work = tmp_path / "zn.endf"
    shutil.copy(ZN, work)
    result = run_cli(["replace", "-n", "3/2/AWR", str(modified_cu), str(work)])
    assert result.returncode == 0
    assert parse_tape_file(work, parser=parser)[0][3][2]["AWR"] == 62.389


def test_replace_multi_material_with_selector(
    donor_tape, two_material_tape, parser, tmp_path
):
    """A #-prefixed path replaces a field of the selected material only."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["replace", "-n", "#1/3/2/AWR", str(donor_tape), str(work)])
    assert result.returncode == 0
    materials = parse_tape_file(work, parser=parser)
    assert materials[1][3][2]["AWR"] == 999.0
    assert materials[0][3][2]["AWR"] == 62.389


def test_replace_multi_material_bare_path_rejected(two_material_tape, tmp_path):
    """On a multi-material destination a selector-less path is rejected."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["replace", "-n", "3/2/AWR", str(CU), str(work)])
    assert result.returncode == 1
    assert "2 materials" in result.stderr


def test_replace_whole_mf(donor_tape, two_material_tape, parser, tmp_path):
    """An MF-depth path replaces an entire MF file of the selected material."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["replace", "-n", "#1/3", str(donor_tape), str(work)])
    assert result.returncode == 0
    materials = parse_tape_file(work, parser=parser)
    # MF3 of material #1 came from the donor ...
    assert materials[1][3][2]["AWR"] == 999.0
    # ... while material #0 and the MF1 of material #1 are untouched
    assert materials[0][3][2]["AWR"] == 62.389
    assert materials[1][1][451]["MAT"] == 3025


def test_replace_whole_material(donor_tape, two_material_tape, parser, tmp_path):
    """A material-depth path replaces an entire material."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["replace", "-n", "#1", str(donor_tape), str(work)])
    assert result.returncode == 0
    materials = parse_tape_file(work, parser=parser)
    assert materials[1][3][2]["AWR"] == 999.0
    assert materials[0][3][2]["AWR"] == 62.389


def test_replace_whole_mf_missing_in_source(two_material_tape, parser, tmp_path):
    """Replacing an MF file absent from the source fails with a clear error."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    # MF99 does not exist in the source
    result = run_cli(["replace", "-n", "#0/99", str(CU), str(work)])
    assert result.returncode == 1
    assert "MF=99" in result.stderr


def test_replace_source_path_overrides_source_location(
    two_material_tape, parser, tmp_path
):
    """--source-path reads from a single-material reference into a tape slot."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    # write the AWR of the single-material Cu file into tape material #1
    result = run_cli(
        ["replace", "-n", "#1/3/2/AWR", "--source-path", "3/2/AWR", str(CU), str(work)]
    )
    assert result.returncode == 0
    materials = parse_tape_file(work, parser=parser)
    assert materials[1][3][2]["AWR"] == 62.389  # copied from Cu
    assert materials[1][1][451]["MAT"] == 3025  # still the Zn material


def test_replace_hash_selector_single_material_source_errors(
    two_material_tape, tmp_path
):
    """A #k selector against a single-material source fails cleanly."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    # #1 cannot resolve in the single-material source CU
    result = run_cli(["replace", "-n", "#1/3/2/AWR", str(CU), str(work)])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "replace:" in result.stderr


def test_replace_empty_target_reported_cleanly(tmp_path):
    """An empty target file is reported cleanly, not with a traceback."""
    work = tmp_path / "empty.endf"
    work.write_text("")
    result = run_cli(["replace", "-n", "3/2/AWR", str(CU), str(work)])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "replace:" in result.stderr


def test_replace_path_kind_mismatch_rejected(two_material_tape, tmp_path):
    """The source and target paths must address the same kind of object."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(
        [
            "replace",
            "-n",
            "#0/3/2",
            "--source-path",
            "#0/3/2/AWR",
            str(two_material_tape),
            str(work),
        ]
    )
    assert result.returncode == 1
    assert "same kind" in result.stderr


# --- Phase 14: the insert subcommand ---------------------------------------


def _mats(path, parser):
    return [m[1][451]["MAT"] for m in parse_tape_file(path, parser=parser)]


def test_insert_appends_by_default(two_material_tape, parser, tmp_path):
    """Without --after, the material is appended at the end of the tape."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["insert", "-n", "--source-path", "#0", str(CU), str(work)])
    assert result.returncode == 0
    assert _mats(work, parser) == [2925, 3025, 2925]


def test_insert_after_position(two_material_tape, parser, tmp_path):
    """--after #k places the new material right after material #k."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(
        ["insert", "-n", "--after", "#0", "--source-path", "#0", str(CU), str(work)]
    )
    assert result.returncode == 0
    assert _mats(work, parser) == [2925, 2925, 3025]


def test_insert_from_multi_material_source(two_material_tape, parser, tmp_path):
    """--source-path selects which material of a multi-material source."""
    work = tmp_path / "cu.endf"
    shutil.copy(CU, work)
    result = run_cli(
        [
            "insert",
            "-n",
            "--after",
            "#0",
            "--source-path",
            "#1",
            str(two_material_tape),
            str(work),
        ]
    )
    assert result.returncode == 0
    assert _mats(work, parser) == [2925, 3025]


def test_insert_result_validates(two_material_tape, tmp_path):
    """The tape produced by an insertion is structurally valid."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    assert (
        run_cli(
            ["insert", "-n", "--after", "#0", "--source-path", "#0", str(CU), str(work)]
        ).returncode
        == 0
    )
    assert run_cli(["validate", str(work)]).returncode == 0


def test_insert_section_source_path_rejected(two_material_tape, tmp_path):
    """--source-path must select a whole material, not a section."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(["insert", "-n", "--source-path", "#0/3/2", str(CU), str(work)])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "whole material" in result.stderr


def test_insert_after_out_of_range_clean_error(two_material_tape, tmp_path):
    """An out-of-range --after selector fails cleanly, not with a traceback."""
    work = tmp_path / "tape.endf"
    shutil.copy(two_material_tape, work)
    result = run_cli(
        ["insert", "-n", "--after", "#9", "--source-path", "#0", str(CU), str(work)]
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "insert:" in result.stderr
