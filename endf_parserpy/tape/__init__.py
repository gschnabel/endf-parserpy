############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/16
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Support for ENDF files containing several materials (tapes)."""

from .errors import (
    TapeError,
    TapeStructureError,
    AmbiguousMaterialError,
    SectionParseError,
    SectionRenderError,
    StaleSourceError,
)
from .splitter import split_materials
from .operations import (
    parse_tape,
    iter_parse_tape,
    write_tape,
    FailedMaterial,
)
from .index import TapeIndex, MaterialIndexEntry, SectionIndexEntry
from .address import EndfMaterialPath
from .material import MaterialView
from .endf_file import EndfFile, FailedSection

__all__ = (
    "parse_tape",
    "iter_parse_tape",
    "write_tape",
    "split_materials",
    "FailedMaterial",
    "TapeIndex",
    "MaterialIndexEntry",
    "SectionIndexEntry",
    "EndfFile",
    "EndfMaterialPath",
    "MaterialView",
    "FailedSection",
    "TapeError",
    "TapeStructureError",
    "AmbiguousMaterialError",
    "SectionParseError",
    "SectionRenderError",
    "StaleSourceError",
)
