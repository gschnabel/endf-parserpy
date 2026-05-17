############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/10/06
# Last modified:   2026/05/17
# License:         MIT
# Copyright (c) 2024-2026 International Atomic Energy Agency (IAEA)
#
############################################################

from glob import glob
import os
import sys
from ..cmd_utils import (
    add_common_cmd_parser_args,
    get_endf_parser,
    open_endf_file,
    resolve_material_path,
    export_endf_file,
)
from endf_parserpy import EndfPath, EndfMaterialPath


COMMAND_NAME = "replace"


def add_subparser(subparsers):
    parser_replace = subparsers.add_parser(COMMAND_NAME)
    add_common_cmd_parser_args(parser_replace)
    parser_replace.add_argument(
        "-n",
        "--no-backup",
        action="store_true",
        help="disable creation of backup file (suffix .bak)",
    )
    parser_replace.add_argument(
        "endfpath", type=str, help="EndfPath to object in ENDF file"
    )
    parser_replace.add_argument(
        "sourcefile", type=str, help="file from which object should be retrieved"
    )
    parser_replace.add_argument(
        "destfile",
        nargs="+",
        type=str,
        help="file(s) in which information should be inserted/replaced",
    )


def _is_section_level(raw_path):
    """Whether ``raw_path`` stops at section depth.

    A path that stops at (or above) ``MF/MT`` swaps a whole section; a
    longer path reaches into a section and replaces a single field.
    """
    raw_path = str(raw_path).strip()
    if "#" in raw_path:
        return EndfMaterialPath(raw_path).subpath is None
    return len(EndfPath(raw_path)) <= 2


def perform_action(args):
    assert args["subcommand"] == COMMAND_NAME
    create_backup = not args["no_backup"]
    raw_path = args["endfpath"]
    sourcefile = args["sourcefile"]
    izm = args["ignore_zero_mismatch"]
    izm = False if izm is None else izm
    override_args = {
        "ignore_zero_mismatch": izm,
        "ignore_send_records": True,
        "ignore_missing_tpid": True,
    }
    if not _is_section_level(raw_path):
        # a subtle replacement inside an MF/MT section and not just
        # swapping out the entire MF/MT section: keep the verbatim string
        # representation of the section's other, untouched fields
        override_args["preserve_value_strings"] = True
    parser = get_endf_parser(args, override_args)

    destfiles = []
    for fp in args["destfile"]:
        curfiles1 = glob(fp)
        curfiles2 = [fp]
        if all(f1 == f2 for f1, f2 in zip(curfiles1, curfiles2)):
            if not os.path.exists(fp):
                print(f"File {fp} does not exist", file=sys.stderr)
                sys.exit(1)
        destfiles.extend(glob(fp))
    retcode = _replace_element(
        parser, raw_path, sourcefile, destfiles, create_backup=create_backup
    )
    sys.exit(retcode)


def _replace_element(parser, raw_path, sourcefile, destfiles, create_backup):
    source = open_endf_file(sourcefile, parser)
    obj = source[resolve_material_path(source, raw_path)]
    # detach a section view to a standalone dict so it survives once the
    # source EndfFile goes out of scope (a field path yields a scalar)
    if hasattr(obj, "detach"):
        obj = obj.detach()
    for outfile in destfiles:
        dest = open_endf_file(outfile, parser)
        dest[resolve_material_path(dest, raw_path)] = obj
        export_endf_file(dest, outfile, create_backup)
    return 0
