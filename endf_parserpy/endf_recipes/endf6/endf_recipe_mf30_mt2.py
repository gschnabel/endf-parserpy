############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/12
# Last modified:   2026/05/12
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

# Note on the MT=2 covariance matrix:
#  - Stores the (relative) parameter covariance matrix Rcov as an
#    upper-triangular ragged array. For each row MP=1..NP, NCS[MP]
#    elements are given starting at the diagonal Rcov(MP,MP).
#    Hence the stored values are Rcov(MP, MP+k-1) for k=1..NCS[MP].
#    Suppressed-zero convention: any Rcov(MP, J) with J > MP+NCS[MP]-1
#    is implicitly zero.
#  - PARM[MP] optionally records the numerical value of the MP-th
#    parameter at the point in parameter space where the sensitivities
#    were calculated (manual section 30.3.2). It may also be zero.
#  - The N2 field of each LIST equals the row index MP and is checked
#    against the loop variable i.
#  - The manual (sections 30.2.2 and example LIST records) is slightly
#    inconsistent in its index notation: prose says "the filling of the
#    MP-th row begins with the diagonal element Rcov(MP, MP)" while the
#    example expressions for rows 2 and 3 appear to skip the diagonal.
#    This recipe follows the prose, which is the standard interpretation.

ENDF_RECIPE_MF30_MT2 = """

[MAT, 30, 2/ ZA, AWR, 0, 0, 0, NP] HEAD

for i=1 to NP:
    [MAT, 30, 2/ PARM[i], 0.0, 0, 0, NCS[i], i /
        {Rcov[i, i+k-1]}{k=1 to NCS[i]} ] LIST
endfor

SEND
"""
