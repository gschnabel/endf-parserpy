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

"""Exceptions raised by the multi-material tape interface."""


class TapeError(Exception):
    """Base class for all errors raised by the tape interface."""


class TapeStructureError(TapeError):
    """Raised when the structure of an ENDF tape is malformed.

    Examples are a tape that does not begin with a tape head (TPID)
    record, or a tape that ends in the middle of a material because the
    final MEND or TEND record is missing.
    """
