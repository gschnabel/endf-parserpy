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


def _selector_of(resolved_path):
    """Return the material-selector segment of a resolved path."""
    return resolved_path.strip("/").split("/")[0]


def _extract(endf_file, resolved, label):
    """Return the object addressed by ``resolved`` in ``endf_file``.

    A material- or MF-depth path yields a ``{(MF, MT): section}`` mapping
    of every section it covers; a section- or field-depth path yields the
    detached section dict or the plain field value. The returned
    ``mf_scope`` is the MF number for an MF-depth path, ``None`` for a
    material-depth path, and otherwise unused.
    """
    mp = EndfMaterialPath(resolved)
    if mp.mf is None:
        # whole material
        material = endf_file[_selector_of(resolved)]
        sections = {mfmt: material[mfmt].detach() for mfmt in material.sections()}
        return "material", None, sections
    if mp.mt is None:
        # whole MF file
        material = endf_file[_selector_of(resolved)]
        sections = {
            (mf, mt): material[mf, mt].detach()
            for (mf, mt) in material.sections()
            if mf == mp.mf
        }
        if not sections:
            print(f"{label} has no MF={mp.mf} section to copy", file=sys.stderr)
            sys.exit(1)
        return "mf", mp.mf, sections
    # a section or a field within a section
    obj = endf_file[resolved]
    if hasattr(obj, "detach"):
        obj = obj.detach()
    return "path", None, obj


def _install(endf_file, resolved, kind, mf_scope, obj):
    """Write ``obj`` (as produced by :func:`_extract`) into ``endf_file``."""
    if kind == "path":
        endf_file[resolved] = obj
        return
    # kind is "material" or "mf": replace whole sections so that the
    # destination's covered sections become exactly the source's
    material = endf_file[_selector_of(resolved)]
    for mfmt, section in obj.items():
        material[mfmt] = section
    for mf, mt in list(material.sections()):
        in_scope = mf_scope is None or mf == mf_scope
        if in_scope and (mf, mt) not in obj:
            del material[mf, mt]


def _replace_element(parser, raw_path, sourcefile, destfiles, create_backup):
    source = open_endf_file(sourcefile, parser)
    src_resolved = resolve_material_path(source, raw_path)
    kind, mf_scope, obj = _extract(source, src_resolved, f"source {sourcefile}")
    for outfile in destfiles:
        dest = open_endf_file(outfile, parser)
        dst_resolved = resolve_material_path(dest, raw_path)
        _install(dest, dst_resolved, kind, mf_scope, obj)
        export_endf_file(dest, outfile, create_backup)
    return 0
