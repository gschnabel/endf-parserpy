"""Regression-equivalence tests for ``endf-cli``.

Each case runs an ``endf-cli`` subcommand on single-material fixtures and
asserts that stdout, the exit code and any produced/modified output files
are identical to a golden captured from the CLI *before* multi-material
support was added.  This guards the ``parsefile`` -> ``EndfFile`` refactor:
existing single-material behaviour must not change.

The goldens in ``cli_baseline_goldens/`` were captured once from the
pre-multi-material CLI and must not be regenerated casually.  To
deliberately recapture them, run::

    ENDF_CLI_CAPTURE=1 pytest tests/test_cli_equivalence.py

Output-file hashes are taken modulo a single end-of-file newline (see
``_run_case``), so a tape written by ``EndfFile.export`` compares equal
to one written by the pre-change ``parser.writefile``.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TESTDATA = REPO / "tests" / "testdata"
GOLDEN_DIR = Path(__file__).resolve().parent / "cli_baseline_goldens"

# placeholder -> (fixture file in testdata, name used inside the work dir)
FIXTURES = {
    "cu": ("n_2925_29-Cu-63.endf", "cu.endf"),
    "cu2": ("n_2925_29-Cu-63.endf", "cu2.endf"),
    "zn": ("n_3025_30-Zn-64.endf", "zn.endf"),
}

CASES = [
    {"id": "show_section", "argv": ["show", "3/2", "{cu}"]},
    {"id": "show_value", "argv": ["show", "3/2/AWR", "{cu}"]},
    {"id": "validate_one", "argv": ["validate", "{cu}"]},
    {"id": "validate_many", "argv": ["validate", "{cu}", "{zn}"]},
    # compare on two identical single-material files: the field-by-field
    # diff path of two materials with *different* MAT numbers is no longer
    # an equivalence case -- multi-material `compare` pairs by MAT number,
    # so cross-MAT comparison intentionally changed; it is covered by
    # tests/test_cli_multimaterial.py instead.
    {"id": "compare_equal", "argv": ["compare", "{cu}", "{cu2}"]},
    {"id": "explain_var", "argv": ["explain", "3/2/AWR", "{cu}"]},
    {"id": "match_query", "argv": ["match", "{cu}", "--query", "exists(/3/2)"]},
    {
        "id": "convert_json",
        "argv": ["convert", "{cu}", "out.json", "--to", "json"],
        "outfiles": ["out.json"],
    },
    {
        "id": "update_directory",
        "argv": ["update-directory", "{cu}"],
        "outfiles": ["{cu}"],
    },
    {
        "id": "insert_text",
        "argv": ["insert-text", "{cu}"],
        "stdin": "CLI EQUIVALENCE TEST DESCRIPTION LINE\n",
        "outfiles": ["{cu}"],
    },
    {
        "id": "replace_value",
        "argv": ["replace", "3/2/AWR", "{cu}", "{zn}"],
        "outfiles": ["{zn}"],
    },
]


def _subst(token):
    for placeholder, (_, name) in FIXTURES.items():
        token = token.replace("{" + placeholder + "}", name)
    return token


def _run_case(case, workdir):
    workdir = Path(workdir)
    needed = {ph for tok in case["argv"] for ph in FIXTURES if "{" + ph + "}" in tok}
    for ph in needed:
        src, name = FIXTURES[ph]
        shutil.copy(TESTDATA / src, workdir / name)
    argv = [_subst(t) for t in case["argv"]]
    # Pin the hash seed: some reporting paths (e.g. compare_objects) iterate
    # sets, whose order otherwise varies between processes and would make
    # the captured stdout non-reproducible.
    env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONHASHSEED": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "endf_parserpy.cli.cmd", *argv],
        cwd=workdir,
        input=case.get("stdin"),
        env=env,
        capture_output=True,
        text=True,
    )
    result = {"stdout": proc.stdout, "returncode": proc.returncode, "files": {}}
    for outfile in case.get("outfiles", []):
        data = (workdir / _subst(outfile)).read_bytes()
        # Normalize the end-of-file newline before hashing: EndfFile.export
        # terminates the tape with a newline whereas the pre-change CLI's
        # parser.writefile did not. That single trailing byte is the only
        # intended difference, so it must not register as a regression.
        data = data.rstrip(b"\n") + b"\n"
        result["files"][outfile] = hashlib.sha256(data).hexdigest()
    return result


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_cli_equivalence(case, tmp_path):
    result = _run_case(case, tmp_path)
    golden_file = GOLDEN_DIR / (case["id"] + ".json")
    if os.environ.get("ENDF_CLI_CAPTURE"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden_file.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"captured baseline golden for {case['id']}")
    golden = json.loads(golden_file.read_text())
    assert result["returncode"] == golden["returncode"]
    assert result["stdout"] == golden["stdout"]
    assert result["files"] == golden["files"]
