############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/15
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Support for ENDF files containing several materials (tapes)."""

from .errors import TapeError, TapeStructureError
from .splitter import split_materials
from .operations import (
    parse_tape,
    iter_parse_tape,
    write_tape,
    FailedMaterial,
)

__all__ = (
    "parse_tape",
    "iter_parse_tape",
    "write_tape",
    "split_materials",
    "FailedMaterial",
    "TapeError",
    "TapeStructureError",
)
