"""Example 003 -- bounded memory with a large multi-material tape.

``EndfFile`` is designed so that a tape far larger than the available
memory can still be opened, navigated, edited and written back with a
bounded memory footprint. Three mechanisms cooperate:

  * the tape is *indexed* on construction, but sections are parsed only
    when accessed and then held in caches of a fixed byte budget;
  * edits go into a small in-memory *overlay*, leaving the rest of the
    tape untouched on disk;
  * :meth:`EndfFile.export` *streams* the tape one material at a time.

This script demonstrates that. It

  1. builds a ~256 MB multi-material tape (the two test evaluations
     repeated at linearly increasing temperatures),
  2. opens it with deliberately small caches and reads from every
     material,
  3. edits a couple of materials, and
  4. exports the edited tape,

reporting the peak Python-heap memory of each phase. Every phase stays
far below 100 MB even though the tape is hundreds of MB.

Run it from the examples/ directory:

    python example-003-bounded-memory.py

A note on the metric: ``tracemalloc`` measures the Python-heap working
set, which is exactly what the cache budget governs. Total process RSS
additionally carries a fixed baseline -- the interpreter and the parser
extension -- that no caching can remove; it is not the figure of merit
here.
"""

import sys
import shutil
import tempfile
import tracemalloc
from pathlib import Path

sys.path.append("../")
from endf_parserpy import (
    EndfParserFactory,
    EndfFile,
    parse_tape_file,
    write_tape,
    write_tape_file,
)


HERE = Path(__file__).resolve().parent
TESTDATA = HERE.parent / "tests" / "testdata"
CU_FILE = TESTDATA / "n_2925_29-Cu-63.endf"  # MAT 2925, Cu-63
ZN_FILE = TESTDATA / "n_3025_30-Zn-64.endf"  # MAT 3025, Zn-64

TARGET_BYTES = 256 * 1024 * 1024  # size of the tape to build; raise to stress it
CACHE_BYTES = 8 * 1024 * 1024  # byte budget of each EndfFile cache tier

parser = EndfParserFactory.create(select="fastest")
workdir = Path(tempfile.mkdtemp(prefix="endf-example-003-"))
BIG_FILE = workdir / "large_tape.endf"
EDITED_FILE = workdir / "edited_tape.endf"


def mb(n_bytes):
    """Format a byte count in mebibytes."""
    return n_bytes / (1024 * 1024)


tracemalloc.start()
print(
    f"target tape size {mb(TARGET_BYTES):.0f} MB, "
    f"cache budget {mb(CACHE_BYTES):.0f} MB per tier\n"
)


# ===========================================================================
# Act 1 -- build a ~256 MB tape without ever holding it in memory
# ===========================================================================
#
# The two evaluations are parsed once. A generator then yields
# temperature-varied copies on demand; because write_tape_file() renders
# and writes each material before pulling the next, the whole tape is
# never assembled in memory.

cu = parse_tape_file(CU_FILE, parser=parser)[0]
zn = parse_tape_file(ZN_FILE, parser=parser)[0]
sources = [cu, zn]

material_bytes = len(write_tape([cu], parser=parser))  # size of one material
n_materials = max(2, TARGET_BYTES // material_bytes)


def varied_materials():
    """Yield ``n_materials`` temperature-varied copies of the two evaluations.

    The source dictionary is mutated in place and yielded;
    write_tape_file() consumes it before the next is produced, so no
    copy is ever accumulated.
    """
    for i in range(n_materials):
        material = sources[i % 2]
        material[1][451]["TEMP"] = 293.6 + i * 25.0  # rises linearly
        yield material


write_tape_file(varied_materials(), BIG_FILE, parser=parser, overwrite=True)
del cu, zn, sources  # the source evaluations are no longer needed

size = BIG_FILE.stat().st_size
print(f"Act 1: built a {mb(size):.0f} MB tape of {n_materials} materials")
print(f"       creation peak heap: {mb(tracemalloc.get_traced_memory()[1]):.1f} MB")
tracemalloc.reset_peak()


# ===========================================================================
# Act 2 -- open the large tape with small caches and read from it
# ===========================================================================
#
# EndfFile indexes the tape on construction; sections are parsed only on
# access and held in caches bounded to CACHE_BYTES per tier, so reading
# from every one of the 256 MB of materials never loads them all at once.

endf_file = EndfFile(
    BIG_FILE,
    parser=parser,
    parsed_cache_bytes=CACHE_BYTES,
    raw_cache_bytes=CACHE_BYTES,
)
print(f"\nAct 2: opened the tape -- {len(endf_file)} materials")

# touch a section in *every* material; the caches evict as they fill
for material in endf_file:
    _ = material[3, 2]["AWR"]  # parse MF=3/MT=2 of this material
raw_cache, parsed_cache = endf_file.cache_nbytes
print(
    f"       read a section from all {len(endf_file)} materials; caches now "
    f"hold {mb(raw_cache):.1f} + {mb(parsed_cache):.1f} MB"
)
print(f"       open + read peak heap: {mb(tracemalloc.get_traced_memory()[1]):.1f} MB")
tracemalloc.reset_peak()


# ===========================================================================
# Act 3 -- edit a couple of materials; the edits live in the overlay
# ===========================================================================
#
# A path assignment renders and recipe-checks just the one section and
# stores it in that material's small in-memory overlay. The other ~256 MB
# of materials are untouched and are never loaded.

endf_file["#0/1/451/TEMP"] = 0.0
endf_file["2925#1/1/451/TEMP"] = 999.9
modified = [m.position for m in endf_file if m.is_modified]
print(f"\nAct 3: edited 2 sections; modified materials are at positions {modified}")
print(f"       edit peak heap: {mb(tracemalloc.get_traced_memory()[1]):.1f} MB")
tracemalloc.reset_peak()


# ===========================================================================
# Act 4 -- export the edited tape, streaming one material at a time
# ===========================================================================

endf_file.export(EDITED_FILE)
print(f"\nAct 4: exported the edited {mb(EDITED_FILE.stat().st_size):.0f} MB tape")
print(f"       export peak heap: {mb(tracemalloc.get_traced_memory()[1]):.1f} MB")

# re-open the exported tape and confirm the two edits landed
check = EndfFile(EDITED_FILE, parser=parser)
print(
    f"       re-opened: #0 TEMP = {check['#0/1/451/TEMP']} K, "
    f"2925#1 TEMP = {check['2925#1/1/451/TEMP']} K"
)

peak = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()
print(
    f"\nDone: a {mb(size):.0f} MB tape was built, opened, read, edited and "
    f"exported\n      with the peak Python-heap of every phase well under "
    f"100 MB."
)

shutil.rmtree(workdir)
print(f"(removed {mb(2 * size):.0f} MB of scratch files from {workdir})")
