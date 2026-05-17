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
    export_endf_file,
)
from endf_parserpy import update_directory


COMMAND_NAME = "update-directory"


def add_subparser(subparsers):
    parser_update_dir = subparsers.add_parser(COMMAND_NAME)
    add_common_cmd_parser_args(parser_update_dir)
    parser_update_dir.add_argument(
        "-n",
        "--no-backup",
        action="store_true",
        help="disable creation of backup file (suffix .bak)",
    )
    parser_update_dir.add_argument("file", type=str, help="ENDF file")


def perform_action(args):
    assert args["subcommand"] == COMMAND_NAME
    parser = get_endf_parser(args)
    create_backup = not args["no_backup"]
    _update_mf1mt451_directory(parser, args["file"], create_backup)
    sys.exit(0)


def _update_mf1mt451_directory(parser, file, create_backup):
    endf_file = open_endf_file(file, parser)
    for material in endf_file:
        if (1, 451) not in material.sections():
            continue
        # update_directory() needs a complete single-material tape dict
        # with MF1/MT451 as a parsed mapping; the other sections may stay
        # as their raw on-disk lines, which is what to_tape_dict() yields.
        mat_dict = material.to_tape_dict()
        mat_dict[1][451] = material[1, 451].detach()
        update_directory(mat_dict, parser, read_opts=parser.read_opts)
        endf_file[f"#{material.position}/1/451"] = mat_dict[1][451]
    export_endf_file(endf_file, file, create_backup)
