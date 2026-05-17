############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/04/23
# Last modified:   2026/05/15
# License:         MIT
# Copyright (c) 2024-2026 International Atomic Energy Agency (IAEA)
#
############################################################


from ...errors import EndfParserpyError


class EquationSolveError(EndfParserpyError):
    pass


class VariableMissingError(EquationSolveError):
    pass


class MultipleVariableOccurrenceError(EquationSolveError):
    pass


class ModuloEquationError(EquationSolveError):
    pass


class SeveralUnknownVariablesError(EquationSolveError):
    pass
