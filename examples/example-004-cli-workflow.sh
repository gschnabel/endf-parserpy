#!/usr/bin/env bash
#
# Example 004 -- a realistic end-to-end workflow with the endf-cli tool.
#
# endf-parserpy ships a command-line tool, endf-cli, for common ENDF-6
# operations. This script walks through a complete workflow on a
# multi-material ENDF tape and touches every endf-cli subcommand:
#
#   bundle two evaluations into one tape         (insert-material)
#   inspect it                   (list-materials, show, explain, match)
#   edit it                   (insert-text, replace, update-directory)
#   check and transcode it                 (validate, compare, convert)
#   prune it                                      (remove-material)
#
# It is meant to be read as much as run. Execute it from the examples/
# directory of a source checkout:
#
#     bash example-004-cli-workflow.sh
#
# Once endf-parserpy is installed (pip install endf-parserpy), `endf-cli`
# is a real command on your PATH and the lines below are exactly what you
# would type. Like the other examples, this script exercises the source
# tree it lives in, so the shim below routes `endf-cli` through the local
# package rather than through whatever may be installed.

set -euo pipefail

# --- run endf-cli from this source tree ------------------------------------
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
endf-cli() { PYTHONPATH="$SCRIPT_DIR/.." python -m endf_parserpy.cli.cmd "$@"; }

# --- set up a scratch working directory ------------------------------------
TESTDATA="$SCRIPT_DIR/../tests/testdata"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp "$TESTDATA/n_2925_29-Cu-63.endf" "$WORK/cu.endf"   # Cu-63, MAT 2925
cp "$TESTDATA/n_3025_30-Zn-64.endf" "$WORK/zn.endf"   # Zn-64, MAT 3025
cd "$WORK"

echo "### 1. Bundle two single-material files into one multi-material tape"
# cu.endf already is a one-material tape; insert-material appends the
# material of zn.endf to it. --source-path '#0' picks zn.endf's only
# material. (-n/--no-backup skips the .bak file; drop it to keep one.)
cp cu.endf lib.endf
endf-cli insert-material --no-backup --source-path '#0' zn.endf lib.endf

echo "### 2. List the materials on the tape"
endf-cli list-materials lib.endf

echo "### 3. Validate the structural correctness of the tape"
endf-cli validate lib.endf

echo "### 4. Browse the tape: a material, an MF file, a single field"
endf-cli show '#1'         lib.endf    # material #1: the sections it holds
endf-cli show '#1/3'       lib.endf    # MF=3 of material #1: its MT numbers
endf-cli show '#1/3/2/AWR' lib.endf    # one field of one section

echo "### 5. Explain the meaning of a variable"
endf-cli explain '#1/3/2/AWR' lib.endf

echo "### 6. Find the materials matching a query"
# match follows the grep convention: exit 0 if something matched,
# 1 if nothing did, 2 if a file or material could not be parsed.
if endf-cli match lib.endf --query '/1/451/ZA == 30064'; then
    echo "    -> at least one material matched"
else
    echo "    -> nothing matched (exit $?)"
fi

echo "### 7. Insert a descriptive comment into material #1"
echo "Patched via the endf-cli example workflow." \
    | endf-cli insert-text --no-backup -m '#1' lib.endf

echo "### 8. Restore material #1's MF3/MT2 section from the reference file"
# the target path '#1/3/2' selects the section in the tape; --source-path
# '3/2' addresses it in the single-material reference zn.endf
endf-cli replace --no-backup '#1/3/2' --source-path '3/2' zn.endf lib.endf

echo "### 9. Resync the MF1/MT451 directories after the edits, then revalidate"
endf-cli update-directory --no-backup lib.endf
endf-cli validate lib.endf

echo "### 10. Compare the edited tape against a pristine bundle"
cp cu.endf pristine.endf
endf-cli insert-material --no-backup --source-path '#0' zn.endf pristine.endf
# compare follows the diff convention: exit 0 if equal, 1 if differences
# were found, 2 on error. The inserted comment makes the tapes differ.
if endf-cli compare lib.endf pristine.endf; then
    echo "    -> the tapes are identical"
else
    echo "    -> differences were found (exit $?)"
fi

echo "### 11. Convert the tape to JSON and back, and confirm the round-trip"
endf-cli convert lib.endf lib.json --to json
endf-cli convert lib.json roundtrip.endf --to endf
if endf-cli compare lib.endf roundtrip.endf; then
    echo "    -> the JSON round-trip preserved the tape"
else
    echo "    -> the JSON round-trip introduced differences (exit $?)" >&2
fi

echo "### 12. Remove a material from the tape"
endf-cli remove-material --no-backup '#0' lib.endf
endf-cli list-materials lib.endf

echo
echo "### workflow complete"
