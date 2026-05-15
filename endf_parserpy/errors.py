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

"""Package-wide base exception for endf-parserpy.

Every exception raised by endf-parserpy ultimately derives from
:class:`EndfParserpyError`, so ``except EndfParserpyError`` catches any
library-specific error regardless of which subsystem raised it: the
parsing engine (``ParserException``), the recipe compiler
(``EquationSolveError``) or the multi-material tape interface
(``TapeError``).

This module deliberately has no imports so that every subsystem can
derive its own error hierarchy from it without risking a circular
import.
"""


class EndfParserpyError(Exception):
    """Base class for all exceptions raised by endf-parserpy."""
