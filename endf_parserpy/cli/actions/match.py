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

from endf_parserpy.utils.matching import (
    eval_tree_print,
    expr_parser,
)
from ..cmd_utils import (
    add_common_cmd_parser_args,
    get_endf_parser,
    open_endf_file,
    parsed_material_dict,
)
from glob import glob
import sys


COMMAND_NAME = "match"


def add_subparser(subparsers):
    parser_search = subparsers.add_parser(COMMAND_NAME)
    add_common_cmd_parser_args(parser_search)
    parser_search.add_argument("files", nargs="+", help="files to match")
    parser_search.add_argument("--query", "-q", type=str, help="search expression")


def perform_action(args):
    assert args["subcommand"] == COMMAND_NAME
    parser = get_endf_parser(args)
    files = []
    expr = args["query"]
    tree = expr_parser.parse(expr)
    for fp in args["files"]:
        files.extend(glob(fp))
    retcode = _match_endf_files(parser, files, tree)
    sys.exit(retcode)


def _match_endf_files(parser, files, tree):
    any_failed = False
    for file in files:
        try:
            endf_file = open_endf_file(file, parser, on_error="raise")
        except Exception:  # noqa: BLE001
            any_failed = True
            print(f"parsing failed: {file}")
            continue
        multi = len(endf_file) > 1
        for material in endf_file:
            label = file
            if multi:
                label = f"{file} (material #{material.position}, MAT {material.mat})"
            try:
                endf_dict = parsed_material_dict(material)
            except Exception:  # noqa: BLE001
                any_failed = True
                print(f"parsing failed: {label}")
                continue
            opts = {"filename": label, "print": "match"}
            eval_tree_print(tree, endf_dict, opts)

    retcode = 1 if any_failed else 0
    return retcode
