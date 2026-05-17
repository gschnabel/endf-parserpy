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
