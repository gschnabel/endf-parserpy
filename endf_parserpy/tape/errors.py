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

from ..errors import EndfParserpyError


class TapeError(EndfParserpyError):
    """Base class for all errors raised by the tape interface."""


class TapeStructureError(TapeError):
    """Raised when the structure of an ENDF tape is malformed.

    Examples are a tape that does not begin with a tape head (TPID)
    record, or a tape that ends in the middle of a material because the
    final MEND or TEND record is missing.
    """


class AmbiguousMaterialError(TapeError, LookupError):
    """Raised when a MAT number matches several materials.

    PENDF/GENDF tapes repeat the same MAT number at different
    temperatures. A lookup by MAT number then needs an ``occurrence``
    index to select among them.

    This is a lookup failure, so it also derives from the built-in
    :class:`LookupError`; code that handles lookup errors generically
    can catch it that way.
    """


class SectionParseError(TapeError):
    """Raised when a section fails to parse and ``on_error="raise"``."""


class StaleSourceError(TapeError):
    """Raised when the source file changed after its index was built."""
