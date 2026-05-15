# Implementation Plan — Multi-Material Tapes & Lazy Indexed Access

Status: **DRAFT FOR REVIEW**
Branch: `feature/multi-material-lazy-tape`
Target version: additive feature, no change to existing API.

---

## 1. Motivation

endf-parserpy today parses exactly one material per file (README: *"the package
does not support several materials in a single ENDF-6 file"*). An ENDF-6 *tape*
may legally contain many materials, each terminated by a MEND record, the whole
tape terminated by TEND. This excludes:

* multi-material library tapes;
* **PENDF / GENDF** files, where the *same* MAT number is repeated once per
  temperature (NJOY BROADR/GROUPR output).

This plan adds (a) multi-material parse/write and (b) an optional lazy,
indexed, memory-bounded access mode — without changing any existing behaviour.

---

## 2. Settled design decisions

These were agreed during design review and are treated as fixed inputs:

| # | Decision |
|---|----------|
| D1 | A tape is an **ordered list** of materials. Position is the canonical identity; MAT number is a *secondary* lookup. Never key the result by MAT. |
| D2 | Addressing notation: `MAT`, `MAT#k`, `#k`. `#` selects the **zero-based** k-th member of the candidate set to its left (`9225#1` = 2nd material with MAT 9225; `#5` = 6th material on the tape). Temperature is **not** in the address grammar — it is a query. |
| D3 | `parse`/`parsefile`/`write`/`writefile` semantics **do not change at all**. Everything here is additive. |
| D4 | Existing eager `write()` already round-trips a mix of parsed (`dict`) and raw (`list[str]`) sections — reused unchanged. |
| D5 | Lazy access uses a **3-tier model**: index (always resident) / raw section text (evictable, re-read from disk) / parsed section (evictable, re-derived from raw). |
| D6 | Tier-2 (parsed) cache: clean entries are LRU-evictable, **weighted by raw-text byte size**; dirty entries are pinned; eviction skips entries still referenced externally (weakref guard). |
| D7 | The structural index is **recipe-free**. It reads only structural fields (MAT/MF/MT control fields, HEAD-record `C1=ZA`/`C2=AWR`, byte spans). Semantic fields (e.g. temperature) are resolved lazily via the recipe. |
| D8 | Semantic lookup is generalised: a caller supplies an extended `EndfPath`; the engine parses only the section the path's structural prefix identifies. |
| D9 | **Full in-memory structural editing** (add/delete/reorder materials and sections) is in scope for v1. |
| D10 | `on_error` policy collapses to two values: `raise` and `mark`. `skip` is `mark` + an iteration filter. Default for tapes: `mark`. |
| D11 | Byte-exact round-trip is guaranteed for **raw-kept MT sections only**; parsed sections are re-rendered canonically. Line endings normalised to **LF**; inter-material blank lines not preserved. |
| D12 | Entry point: a new `EndfTape` class constructed directly (not via `EndfParserFactory`). It *accepts* a factory-made parser as an injected engine. |

---

## 3. Architecture & layering

```
            ┌─────────────────────────────────────────────┐
            │  EndfTape  (new, stateful, file-bound)       │  lazy/cache/query/edit
            └───────────────┬─────────────────┬───────────┘
                            │ uses            │ uses
            ┌───────────────▼──────┐   ┌──────▼─────────────────┐
            │ tape splitter +      │   │ EndfParserPy /         │  section-parsing
            │ structural indexer   │   │ EndfParserCpp (engine) │  engine (UNCHANGED)
            └───────────────┬──────┘   └────────────────────────┘
                            │ depends only on
            ┌───────────────▼──────────────────────────────────┐
            │ structural ENDF invariants                        │
            │ (record framing, control fields, HEAD C1/C2)      │
            └───────────────────────────────────────────────────┘
```

**Dependency rule (hard invariant):** the splitter/indexer depend on *nothing*
recipe-related. The recipe layer depends on structural. `EndfTape` depends on
both. The arrow never points upward — the index must never import a recipe.

---

## 4. New & changed files

### New modules (under `endf_parserpy/`)

| File | Contents |
|------|----------|
| `tape/__init__.py` | public exports: `EndfTape`, `parse_tape`, `write_tape`, `iter_parse_tape` |
| `tape/splitter.py` | `split_materials(lines)` — lexical tape → per-material chunks |
| `tape/index.py` | `TapeIndex`, `MaterialIndexEntry`, `SectionIndexEntry`; the structural scanner |
| `tape/cache.py` | `_WeightedSectionCache` (clean LRU + weakref guard), dirty store |
| `tape/material.py` | `MaterialView`, `_MaterialSections` (MutableMapping for structural-edit detection) |
| `tape/endf_tape.py` | `EndfTape` — lifecycle, lazy access, query, editing, write |
| `tape/address.py` | extended-address parsing (`MAT`, `MAT#k`, `#k`) → resolution against index |
| `tape/errors.py` | `AmbiguousMaterialError`, `SectionParseError`, `TapeStructureError`, `StaleSourceError` |

### Functions added to existing public surface

| File | Addition |
|------|----------|
| `endf_parserpy/__init__.py` | re-export `EndfTape`, `parse_tape`, `write_tape`, `iter_parse_tape` |
| `endf_parserpy/utils/accessories.py` | extend `EndfPath` to accept an optional leading material component with `#k` |

### Minimal changes to existing files (additive, behaviour-preserving)

| File | Change | Risk |
|------|--------|------|
| `interpreter/endf_parser.py` | `write()`/`writefile()` gain `include_tpid=True`, `include_tend=True` keyword args (default `True` = today's behaviour). The TPID block and the TEND block (`endf_parser.py:1144-1157`) become conditional. | very low — defaults preserve output |
| `cpp_parsers/endf_parser_cpp.py` | mirror the same two kwargs on `write()`/`writefile()` | very low |
| `endf_parser_base.py` | document the two new kwargs in the abstract signature | none |

No change to `parse`, `parsefile`, `split_sections`, the recipe engine, or the
C++ generated code.

---

## 5. Phased delivery

Each phase is independently reviewable and mergeable. Phase 1 already removes
the documented limitation; later phases add the lazy/indexed/editing layers.

### Phase 1 — Eager multi-material parse/write  *(≈3 days)*

Goal: parse and write tapes with N materials, fully eager, no index/cache.

* `split_materials(lines)` in `tape/splitter.py`:
  purely lexical. Reads `MAT`(67–70)/`MF`(71–72)/`MT`(73–75) per line, splits at
  each MEND (`MAT=0,MF=0,MT=0`), stops at TEND (`MAT=-1`). Each chunk is emitted
  as a self-contained single-material tape: `[TPID] + material_lines + [TEND]`.
  Lossless — never inspects line content.
* `parse_tape(source, *, parser=None, exclude=None, include=None, on_error="mark")`
  → `list` of per-material dicts (each identical in shape to today's
  `parsefile` result). Calls the **unchanged** engine per chunk.
* `iter_parse_tape(filename, ...)` → generator yielding one parsed material at a
  time; peak memory bounded by the largest single material. `parse_tape` is
  `list(iter_parse_tape(...))`.
* `write_tape(materials, out=None, *, include=None, exclude=None)`:
  emits the TPID once, each material body + its MEND, one final TEND — using the
  new `include_tpid`/`include_tend` kwargs on the engine's `write()`.
* `include`/`exclude` accept today's MF / `(MF,MT)` tuples (apply to *all*
  materials) **and** extended-address strings (`"9225#1/3"`) to scope per
  material. Tuple ambiguity (is `(9225,3)` MAT/MF or MF/MT?) is avoided by
  keeping tuples MAT-less and using the path string form for MAT scoping.
* `on_error`: `raise` aborts; `mark` keeps the failed material as a
  `FailedMaterial` object exposing `.exception` and `.raw_lines`.

Deliverable: README limitation note removed; `tests/test_multimaterial.py`.

### Phase 2 — Structural index  *(≈2 days)*

Goal: scan a tape into a recipe-free index without parsing section bodies.

* `TapeIndex.from_file(path)` — one linear pass, refactored from the structural
  half of `split_sections` (`endf_utils.py:459`). Per material records a
  `MaterialIndexEntry`:
  * `position` (0-based), `mat`, `za`, `awr` — `za`/`awr` from HEAD `C1`/`C2`
    (universal, recipe-free);
  * `byte_offset`, `byte_length` of the whole material;
  * `sections`: `{(mf, mt): SectionIndexEntry(offset, length, line_count)}`.
* Secondary maps: `mat -> [positions]`, `za -> [positions]`.
* Source-identity stamp: `(st_size, st_mtime_ns)` captured at scan time for
  optional staleness checks.
* The index is immutable and cheaply picklable (plain dataclasses).

Deliverable: `tests/test_tape_index.py` — index vs. known fixtures, PENDF tape
with repeated MAT.

### Phase 3 — `EndfTape` lazy access + 3-tier cache  *(≈1 week)*

Goal: the stateful lazy class.

* `EndfTape(filename, *, parser=None, mode="index", parsed_cache_bytes=64<<20,
  raw_cache_bytes=64<<20, on_error="mark", verify_source=False)`.
  `parser` defaults to `EndfParserFactory.create(select="fastest")`.
  `mode` ∈ `{"index", "load_raw", "parse_all"}`.
* Mapping protocol over the extended address; `tape[i]` → `MaterialView`;
  `MaterialView[mf, mt]` → parsed section.
* Access path: dirty store → Tier-2 LRU → raw (Tier-1 → disk) → parse via engine.
* `_WeightedSectionCache`: `OrderedDict`, weight = raw-text byte size (free —
  taken from the index `SectionIndexEntry`). Evict LRU non-dirty,
  non-externally-referenced entries until under budget; a single item larger
  than the budget is admitted alone (with a warning).
* File access: **open/seek/read-span/close per section read** — no shared file
  handle, no shared seek position. A single coarse `threading.Lock` guards the
  cache mutation, making a shared `EndfTape` thread-safe (serialised).
* Picklability: `__getstate__` drops the lock and any handle, keeps
  path + config + index; `__setstate__` rebuilds. Lets an `EndfTape` (with its
  pre-built index) be sent to `ProcessPoolExecutor` workers.
* Convenience: `by_mat(mat, *, occurrence=None)` (raises `AmbiguousMaterialError`
  listing positions if needed), `by_nuclide(za)`, `find(...) -> list`,
  `materials()`, `failures()`, `ok()`.
* `__enter__`/`__exit__`; `unload(address=None)`; `repr` shows MAT + nuclide
  labels per position.

Deliverable: `tests/test_endf_tape_lazy.py` — lazy access, eviction under a
tight budget, weakref-pinned identity, pickling round-trip.

### Phase 4 — `EndfPath` query layer  *(≈3 days)*

Goal: semantic lookup decoupled from the engine.

* Extend `EndfPath` with the leading material component (`address.py` resolves
  `MAT`/`MAT#k`/`#k` against a `TapeIndex` → position). Structural prefix
  (`material/MF/MT`) resolved by the index; suffix walked on the parsed dict.
* `tape.get(path)` — parses exactly one section (cached in Tier 2).
* `tape.build_index(path, *, name=None)` — **explicit, opt-in**; parses the
  prefix section of every material to build a secondary `{value -> [positions]}`
  map. Cost (1 section × N materials) is documented at the call site.
* `tape.find(path, predicate)` / `find(**{path: value})`; float comparisons
  (e.g. temperature) take a tolerance. Failed sections honour `on_error`.
* Optional batteries: `endf_parserpy/tape/common_paths.py` — a small, isolated,
  opt-in module of curated paths (`TEMP_ENDF`, `TEMP_PENDF`, …). Semantic
  knowledge lives here, never in the engine.

Deliverable: `tests/test_tape_query.py` — temperature disambiguation on a
multi-temperature PENDF fixture.

### Phase 5 — In-memory structural editing & write-back  *(≈1 week)*

Goal: add/delete/reorder materials and sections, then write.

* `_MaterialSections` and the tape-level material collection are
  `MutableMapping` subclasses intercepting new-key / `__delitem__` / reorder →
  set a `structure_modified` flag on the affected material/tape.
* Detection boundary: *structural* = change to the set/order of
  `(material, MF, MT)` sections; *value* = anything below a section (tracked by
  a per-section dirty bit, set via `__setitem__` or a `TrackingDict` wrapper —
  the engine already ships `TrackingDict`).
* The index stays valid throughout: it is immutable, identity-keyed, and refers
  to the *original* file. Deleting/adding in memory never moves on-disk bytes of
  other sections. New sections have no disk tier (born in-memory/dirty).
* Write-back via **temp file + atomic `os.replace`**. On POSIX an open lazy
  handle keeps the old inode alive, so writing back to the *same path* works
  without full materialisation. On Windows: close-and-reopen (or materialise)
  first — documented, handled.
* Directory regeneration: MF1/MT451's directory is **per-material, intra-MAT**.
  On write, regenerate it (`utils/endf6_plumbing.update_directory`) for any
  material containing ≥1 modified section, because both structural edits and
  record-count-changing value edits stale the `NC` entries. Opt-out flag for
  users wanting verbatim output.
* Write preserves original material and section order.

Deliverable: `tests/test_tape_editing.py` — add/delete/reorder, same-path
save, directory regeneration, mixed dirty/clean round-trip.

---

## 6. Round-trip contract

* A raw-kept MT section (parsed with `exclude`, or no recipe available, or never
  accessed in lazy mode) → **byte-identical content lines**, copied verbatim.
* A parsed/dirty MT section → canonical re-render via the recipe + `write_opts`.
* Line endings normalised to LF; inter-material blank lines dropped.
* Therefore: a tape parsed with `exclude=(everything)` and written back is
  byte-identical modulo line endings. This is the verbatim-copy mode and is the
  basis of the strongest round-trip test.

---

## 7. C++ backend

* Phase 1/parse_tape: each per-material chunk is a valid single-material tape →
  fed to the **unchanged** `EndfParserCpp.parse(str)` (`endf_parser_cpp.py:212`).
  No C++ changes, no recompilation.
* Phase 3/lazy single-section parse: synthesise a minimal valid mini-tape
  (`TPID + HEAD…SEND + FEND + MEND + TEND`) around the section lines and pass it
  to the C++ `parse()`. Zero C++ changes.
* **Measure-then-decide:** if the mini-tape construction + pybind boundary
  crossing per section proves to dominate in lazy workloads, *then* evaluate a
  generated C++ "parse-one-section" entry point. Not in scope for v1; a
  benchmark in `benchmarks/` will quantify the overhead.

---

## 8. Testing strategy

* Unit tests per phase (listed above).
* Fixtures: small hand-built 2- and 3-material tapes; a real multi-temperature
  PENDF tape; a tape with a deliberately malformed material (for `on_error`).
* **Round-trip suite:** parse-with-full-exclude → `write_tape` → assert
  byte-identical (modulo LF) on a multi-material fixture.
* **Cross-check:** `parse_tape` of an N-material tape vs. N separate
  single-material `parsefile` calls on the split chunks — must be identical.
* **Memory test:** `iter_parse_tape` over a large tape with an assertion on peak
  RSS staying bounded.
* Property test: index offsets — reading each section by its indexed
  `(offset,length)` must reproduce the splitter's chunking.
* CI: add a `multimaterial` test marker; run on the existing matrix.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Blank lines / padding between materials break the splitter | explicit policy: inter-material blank lines are consumed and not preserved (D11); covered by a fixture |
| Same-path write while a lazy handle is open | temp file + atomic replace; POSIX inode semantics; Windows path documented |
| Mini-tape per-section overhead negates C++ speed | Phase-7 benchmark; measure-then-decide |
| Parsed-memory cap is only a proxy (raw-byte weight) | documented as a tuning knob, not an RSS guarantee; per-MF calibration is a possible v2 refinement |
| Stale `NC` in MF1/MT451 directory after edits | regenerate directory for any material with modified sections |
| Source file changed under a long-lived `EndfTape` | opt-in `verify_source` re-stats `(size,mtime)`; raises `StaleSourceError` |

---

## 10. Effort estimate

| Phase | Estimate |
|-------|----------|
| 1 — eager multi-material | ~3 days |
| 2 — structural index | ~2 days |
| 3 — lazy `EndfTape` + cache | ~1 week |
| 4 — `EndfPath` query layer | ~3 days |
| 5 — structural editing + write-back | ~1 week |
| docs, examples, CI polish | ~3 days |
| **Total** | **~4–5 weeks** |

Phases 1–2 are low-risk and independently shippable. Phases 3–5 are additive —
a new class layered over an unchanged engine — so risk to existing behaviour is
near zero throughout.

---

## 11. Open items for reviewer

1. Module location: `endf_parserpy/tape/` (assumed here) vs. another name.
2. Should `iter_parse_tape` yield `(MaterialView, errors)` or bare dicts in
   Phase 1 (before `EndfTape` exists)? Currently: bare dicts + `FailedMaterial`.
3. Public name: `EndfTape` vs. `EndfFile` vs. `EndfMaterialTape`.
4. Whether `common_paths.py` ships in v1 or is deferred to a follow-up.
