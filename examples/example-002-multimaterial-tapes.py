"""Example 002 -- working with multi-material ENDF tapes.

An ENDF-6 file may hold several materials one after another; such a file
is traditionally called a *tape*. This script walks through the
multi-material interface of endf-parserpy from end to end:

  Act 1  build a combined tape from two evaluations, each stored at its
         original and at a varied temperature        (eager tape API)
  Act 2  open the combined tape and explore it: indexing, queries and
         EndfMaterialPath-based access            (EndfFile, eager mode)
  Act 3  edit the tape through live write-through views, add and
         reorder materials, then export it      (EndfFile, deferred mode)

It is not a realistic evaluation workflow -- varying a temperature field
stands in for the real cross-section processing -- but it exercises the
key ingredients of one. Run it from the examples/ directory:

    python example-002-multimaterial-tapes.py
"""

import sys
import copy
from pathlib import Path

sys.path.append("../")
from endf_parserpy import (
    EndfParserFactory,
    EndfFile,
    parse_tape_file,
    write_tape_file,
)
from endf_parserpy.tape import AmbiguousMaterialError


HERE = Path(__file__).resolve().parent
TESTDATA = HERE.parent / "tests" / "testdata"
CU_FILE = TESTDATA / "n_2925_29-Cu-63.endf"  # MAT 2925, Cu-63
ZN_FILE = TESTDATA / "n_3025_30-Zn-64.endf"  # MAT 3025, Zn-64
COMBINED = HERE / "example-002-combined.endf"  # written by Act 1
FINAL = HERE / "example-002-final.endf"  # written by Act 3

parser = EndfParserFactory.create(select="fastest")


def at_temperature(material, temp):
    """Return a deep copy of a material dict with its MF1/MT451 TEMP set.

    The temperature of an evaluation is stored in the descriptive
    MF=1/MT=451 section. Editing one scalar field is the simplest
    possible variation; a real workflow would vary the cross sections
    themselves. A deep copy keeps the original material untouched.
    """
    varied = copy.deepcopy(material)
    varied[1][451]["TEMP"] = temp
    return varied


# ===========================================================================
# Act 1 -- build a combined multi-material tape (eager tape API)
# ===========================================================================
#
# parse_tape_file() reads an ENDF file into a list of material
# dictionaries (here each file holds a single material); its companion
# write_tape_file() assembles a list of materials back into one tape.
# Both come as a memory/file pair -- parse_tape()/write_tape() do the
# same with an in-memory ENDF-6 string.

cu = parse_tape_file(CU_FILE, parser=parser)[0]
zn = parse_tape_file(ZN_FILE, parser=parser)[0]
print(
    f"Act 1: loaded Cu-63 (TEMP={cu[1][451]['TEMP']} K) "
    f"and Zn-64 (TEMP={zn[1][451]['TEMP']} K)"
)

# Store each evaluation at its original temperature and at 600 K. The
# combined tape then repeats every MAT number -- just like a PENDF tape,
# which carries the same material once per temperature.
materials = [
    cu,  # MAT 2925, original temperature
    at_temperature(cu, 600.0),  # MAT 2925, 600 K
    zn,  # MAT 3025, original temperature
    at_temperature(zn, 600.0),  # MAT 3025, 600 K
]
write_tape_file(materials, COMBINED, parser=parser, overwrite=True)
print(f"Act 1: wrote a {len(materials)}-material tape -> {COMBINED.name}")


# ===========================================================================
# Act 2 -- explore the combined tape (EndfFile, eager mode)
# ===========================================================================
#
# EndfFile indexes the tape on construction and parses an individual
# section only when it is accessed. The default check_edits="eager" mode
# is ideal for exploration: a retrieved section is a read-only view.

endf_file = EndfFile(COMBINED, parser=parser)
print(f"\nAct 2: opened {COMBINED.name} -- {len(endf_file)} materials")
for material in endf_file:
    # material is a MaterialView; material[mf, mt] yields a section view
    temp = material[1, 451]["TEMP"]
    print(
        f"  position {material.position}: MAT={material.mat} "
        f"ZA={material.za} TEMP={temp} K"
    )

# --- secondary lookups -----------------------------------------------------
# Each MAT number now occurs twice, so a bare by_mat() is ambiguous ...
try:
    endf_file.by_mat(2925)
except AmbiguousMaterialError as exc:
    print(f"\n  by_mat(2925) is ambiguous: {exc}")
# ... and an occurrence index picks one copy.
cold_cu = endf_file.by_mat(2925, occurrence=0)
print(f"  by_mat(2925, occurrence=0) -> position {cold_cu.position}")
za_hits = [m.position for m in endf_file.by_za(29063)]
print(f"  by_za(29063) -> positions {za_hits}")

# --- indexing and querying -------------------------------------------------
# build_index() maps each value of a section field to the positions of
# the materials carrying it.
by_temp = endf_file.build_index("1/451/TEMP")
print(f"\n  temperature index: {by_temp}")
# A list of section paths builds a composite index, keyed on the tuple
# of the values -- here (ZA, TEMP).
by_za_temp = endf_file.build_index(["1/451/ZA", "1/451/TEMP"])
print(f"  (ZA, TEMP) index:  {by_za_temp}")
# query() returns the materials whose field matches a value.
hot = endf_file.query("1/451/TEMP", 600.0)
print(f"  query TEMP == 600 K -> positions {[m.position for m in hot]}")

# --- EndfMaterialPath access ----------------------------------------------
# A material-qualified path addresses data across the whole tape:
#   #k        material at tape position k
#   MAT       the unique material with that MAT number
#   MAT#k     the k-th material carrying that MAT number
# followed by /MF/MT and an optional field path.
print(f"\n  endf_file['#0/1/451/AWR']      = {endf_file['#0/1/451/AWR']}")
print(f"  endf_file['2925#1/1/451/TEMP'] = {endf_file['2925#1/1/451/TEMP']}")
print(f"  '3025#0/1/451' in endf_file    = {'3025#0/1/451' in endf_file}")

# In eager mode a retrieved section is a read-only (frozen) view; it
# guards against accidental edits while exploring.
section = endf_file["#0/1/451"]
try:
    section["TEMP"] = 250.0
except TypeError:
    print("\n  eager mode: a retrieved section is read-only")
# To edit in eager mode, assign through a path; the result is rendered
# and recipe-checked immediately, so a malformed edit fails right here.
endf_file["#0/1/451/TEMP"] = 250.0
print(
    f"  path assignment: endf_file['#0/1/451/TEMP'] is now {endf_file['#0/1/451/TEMP']}"
)
# (this endf_file is just an exploration handle -- it is not exported)


# ===========================================================================
# Act 3 -- edit the tape: live views, new materials, reordering
# ===========================================================================
#
# Re-open the tape with check_edits="deferred". A retrieved section is
# now a live write-through view: assigning into it edits the tape in
# place, exactly like an EndfDict. (Opening the file again also shows
# that EndfFile never mutates the file on disk by itself.)

endf_file = EndfFile(COMBINED, parser=parser, check_edits="deferred")
print(f"\nAct 3: re-opened {COMBINED.name} in deferred mode")

# A live write-through view -- assign into the retrieved section:
section = endf_file["2925#1/1/451"]  # MF1/MT451 of the 2nd MAT-2925 copy
section["TEMP"] = 590.0
print(f"  live view edit  -> 2925#1 TEMP = {endf_file['2925#1/1/451/TEMP']} K")
# A path-addressed assignment does the same in a single step:
endf_file["3025#1/1/451/TEMP"] = 590.0
print(f"  path edit       -> 3025#1 TEMP = {endf_file['3025#1/1/451/TEMP']} K")

# Append a further material: Cu-63 at 900 K.
endf_file.append_material(at_temperature(cu, 900.0), mat=2925, za=29063)
print(f"  append_material -> {len(endf_file)} materials")

# Reorder so the three Cu-63 copies sit together, ahead of the Zn ones.
# reorder() takes a permutation: the material now at order[i] moves to i.
endf_file.reorder([0, 1, 4, 2, 3])
order = [(m.position, m.mat) for m in endf_file]
print(f"  reorder         -> (position, MAT) = {order}")

# invalid_edits() render-checks every edited section against its ENDF
# recipe and returns the non-conformant ones; an empty list means all
# edits are valid, so "if not endf_file.invalid_edits()" reads as ok.
report = endf_file.invalid_edits()
print(f"  invalid_edits() -> {len(report)} non-conformant section(s)")

# export() writes the edited tape to a file; to_string() returns it as
# an ENDF-6 string instead.
endf_file.export(FINAL, overwrite=True)
print(f"  export()        -> {FINAL.name}")
print(f"  to_string()     -> {len(endf_file.to_string().splitlines())} lines")

# Re-open the exported tape to confirm the round trip.
check = EndfFile(FINAL, parser=parser)
print(
    f"\nDone: {FINAL.name} holds {len(check)} materials at temperatures "
    f"{sorted(check.build_index('1/451/TEMP'))} K"
)
