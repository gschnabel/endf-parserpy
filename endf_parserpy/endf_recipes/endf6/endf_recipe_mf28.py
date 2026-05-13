############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2022/12/14
# Last modified:   2026/05/13
# License:         MIT
# Copyright (c) 2022-2026 International Atomic Energy Agency (IAEA)
#
############################################################

ENDF_RECIPE_MF28 = """

[MAT, 28, 533/ ZA, AWR, 0, 0, NSS, 0] HEAD

for k=1 to NSS:
    NW := 6 * (1 + NTR[k])
    [MAT, 28, 533/ SUBI[k], 0.0, 0, 0, NW, NTR[k]/
        EBI[k], ELN[k], 0.0, 0.0, 0.0, 0.0,
        {SUBJ[k,t], SUBK[k,t], ETR[k,t], FTR[k,t], 0.0, 0.0}{t=1 to NTR[k]}
    ] LIST
endfor
SEND
"""
