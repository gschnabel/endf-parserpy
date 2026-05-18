############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/18
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

    PENDF tapes repeat the same MAT number at different
    temperatures. A lookup by MAT number then needs an ``occurrence``
    index to select among them.

    This is a lookup failure, so it also derives from the built-in
    :class:`LookupError`; code that handles lookup errors generically
    can catch it that way.
    """


class SectionParseError(TapeError):
    """Raised when a section fails to parse and ``on_error="raise"``."""


class SectionRenderError(TapeError):
    """Raised when an edited section fails to render to ENDF-6 text.

    In ``check_edits="eager"`` mode every edited section is rendered
    through the parser's writer right away; a section that no longer
    conforms to its ENDF recipe makes the writer fail, which is reported
    as this error with the writer's own exception kept as its cause. The
    same error is collected by
    :meth:`~endf_parserpy.EndfFile.invalid_edits`.
    """


class StaleSourceError(TapeError):
    """Raised when the source file changed after its index was built."""
