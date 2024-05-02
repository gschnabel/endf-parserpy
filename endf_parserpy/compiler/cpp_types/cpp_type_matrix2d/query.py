############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/04/21
# Last modified:   2024/05/02
# License:         MIT
# Copyright (c) 2024 International Atomic Energy Agency (IAEA)
#
############################################################

from endf_parserpy.compiler.variable_management import find_parent_dict
from ..cpp_varaux import get_cpp_varname


class Query:

    @classmethod
    def is_responsible(cls, vartok, vardict):
        pardict = find_parent_dict(vartok, vardict)
        return pardict[vartok][1] == "Matrix2d" if pardict is not None else False

    @classmethod
    def assemble_extvarname(cls, varname, idxstrs):
        return varname + "(" + ", ".join(idxstrs) + ")"

    @classmethod
    def did_read_var(cls, vartok, vardict, indices=None):
        varname = get_cpp_varname(vartok, vardict)
        return f"{varname}.did_read()"
