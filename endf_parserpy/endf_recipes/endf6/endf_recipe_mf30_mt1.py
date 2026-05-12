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

# Note on the MT=1 directory:
#  - The NDIR CONT records include both "real" entries (MP, MFSEN, MTSEN, NC)
#    and "marker" entries used to delimit data-type and parameter groups:
#      * End-of-MFSEN marker: MP set, MFSEN=0, MTSEN=0, NC=0
#      * End-of-MP    marker: MP=0, MFSEN=0, MTSEN=0, NC=0
#    Both marker types are read here as ordinary directory_entry records;
#    consumers identify them by checking the zero fields after parsing.
#  - The correspondence table (NCTAB records) is optional (NCTAB may be 0).

ENDF_RECIPE_MF30_MT1 = """

[MAT, 30, 1/ ZA, AWR, 0, 0, 0, NP] HEAD
[MAT, 30, 1/ 0.0, 0.0, 0, 0, NDIR, NCTAB] CONT

for i=1 to NDIR:
    (directory_entry[i])
    [MAT, 30, 1/ 0.0, 0.0, MP, MFSEN, MTSEN, NC] CONT
    (/directory_entry[i])
endfor

for i=1 to NCTAB:
    (correspondence_entry[i])
    [MAT, 30, 1/ 0.0, 0.0, MP, LIBF, MATF, MPF] CONT
    (/correspondence_entry[i])
endfor

SEND
"""
