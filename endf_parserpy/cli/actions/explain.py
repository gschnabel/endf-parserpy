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

import sys
from ..cmd_utils import (
    add_common_cmd_parser_args,
    get_endf_parser,
    open_endf_file,
    resolve_material_path,
)
from endf_parserpy import EndfMaterialPath


COMMAND_NAME = "explain"


def add_subparser(subparsers):
    parser_explain = subparsers.add_parser(COMMAND_NAME)
    add_common_cmd_parser_args(parser_explain)
    parser_explain.add_argument(
        "endfpath", type=str, help="EndfPath to the variable that should be explained"
    )
    parser_explain.add_argument("file", type=str, help="ENDF file")


def perform_action(args):
    assert args["subcommand"] == COMMAND_NAME
    parser = get_endf_parser(args, allow_cpp=False)
    _explain_endf_variable(parser, args["endfpath"], args["file"])
    sys.exit(0)


def _explain_endf_variable(parser, endfpath, file):
    endf_file = open_endf_file(file, parser)
    resolved = resolve_material_path(endf_file, endfpath)
    mp = EndfMaterialPath(resolved)
    if mp.mf is None or mp.mt is None:
        print(
            "the explain path must address at least a section, "
            "e.g. '#0/3/2/AWR' or (single-material file) '3/2/AWR'",
            file=sys.stderr,
        )
        sys.exit(1)
    # Parse the addressed section through the EndfFile; this populates the
    # parser's variable_descriptions exactly as parsefile() would.
    parts = resolved.strip("/").split("/")
    section_path = "/".join(parts[:3])
    try:
        endf_file[section_path]
    except Exception as exc:  # noqa: BLE001
        print(f"cannot access section {section_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    # parser.explain() expects a section-relative path (MF/MT/field...);
    # drop the leading material selector.
    parser.explain("/".join(parts[1:]))
