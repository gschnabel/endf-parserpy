# Implementation Plan — Multi-Material Tapes & Lazy Indexed Access

Status: **Phases 1–5 implemented** (multi-material parse/write, structural
index, lazy `EndfFile`, query layer, in-memory editing & write-back)
Branch: `feature/multi-material-lazy-tape`
Target version: additive feature, no change to existing API.

---

## 1. Motivation

endf-parserpy today parses exactly one material per file (README: *"the package
does not support several materials in a single ENDF-6 file"*). An ENDF-6 *tape*
may legally contain many materials, each terminated by a MEND record, the whole
tape terminated by TEND. This excludes:

* multi-material library tapes;
* **PENDF** files, where the *same* MAT number is repeated once per
  temperature (NJOY BROADR output).

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
| D8 | Semantic lookup is generalised: a caller supplies an `EndfMaterialPath`; the engine parses only the section the path's structural prefix identifies. |
| D9 | **Full in-memory structural editing** (add/delete/reorder materials and sections) is in scope for v1. |
| D10 | `on_error` policy collapses to two values: `raise` and `mark`. `skip` is `mark` + an iteration filter. Default for tapes: `mark`. |
| D11 | Byte-exact round-trip is guaranteed for **raw-kept MT sections only**; parsed sections are re-rendered canonically. Line endings normalised to **LF**; inter-material blank lines not preserved. |
| D12 | Entry point: a new `EndfFile` class constructed directly (not via `EndfParserFactory`). It *accepts* a factory-made parser as an injected engine. |
| D13 | `EndfPath` is **not modified**. Today its first component is MF; making it a material would silently break every existing caller. Instead a new `EndfMaterialPath` type = optional material selector + an unchanged `EndfPath`. The two have separate, self-contained grammars: within an `EndfMaterialPath` component 1 is always the material; an `EndfPath` keeps meaning MF/MT/… exactly as before. No backward-compatibility break. |

---

## 3. Architecture & layering

```
            ┌─────────────────────────────────────────────┐
            │  EndfFile  (new, stateful, file-bound)       │  lazy/cache/query/edit
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
recipe-related. The recipe layer depends on structural. `EndfFile` depends on
both. The arrow never points upward — the index must never import a recipe.

---

## 4. New & changed files

### New modules (under `endf_parserpy/`)

| File | Contents |
|------|----------|
| `tape/__init__.py` | public exports: `EndfFile`, `parse_tape`, `write_tape`, `iter_parse_tape` |
| `tape/splitter.py` | `split_materials(lines)` — lexical tape → per-material chunks |
| `tape/index.py` | `TapeIndex`, `MaterialIndexEntry`, `SectionIndexEntry`; the structural scanner |
| `tape/cache.py` | `_WeightedSectionCache` (clean LRU + weakref guard), dirty store |
| `tape/material.py` | `MaterialView`, `_MaterialSections` (MutableMapping for structural-edit detection) |
| `tape/endf_file.py` | `EndfFile` — lifecycle, lazy access, query, editing, write |
| `tape/address.py` | `EndfMaterialPath` (material selector + an unchanged `EndfPath`); parses `MAT` / `MAT#k` / `#k` and resolves it against a `TapeIndex` → position |
| `tape/errors.py` | `AmbiguousMaterialError`, `SectionParseError`, `TapeStructureError`, `StaleSourceError` |

### Functions added to existing public surface

| File | Addition |
|------|----------|
| `endf_parserpy/__init__.py` | re-export `EndfFile`, `EndfMaterialPath`, `parse_tape`, `write_tape`, `iter_parse_tape` |

`endf_parserpy/utils/accessories.py` (`EndfPath`) is **not touched** — see D13.
`EndfMaterialPath` is a new, separate type that *composes* an `EndfPath`, so
existing `EndfPath` behaviour and grammar are unchanged.

### Changes to existing files

**None.** The only edit to existing code is the re-export block in
`endf_parserpy/__init__.py` (above). `parse`, `parsefile`, `write`,
`writefile`, `split_sections`, the recipe engine and the C++ generated code
are all untouched.

The design draft proposed adding `include_tpid` / `include_tend` keyword
arguments to the engine's `write()`. During Phase 1 implementation this was
dropped: the C++ backend emits the whole tape (TPID … TEND) inside C++, so the
keyword approach would have required C++ changes. Instead `write_tape`
**post-processes** each material's writer output — stripping the per-material
TPID and TEND records and re-emitting one of each for the whole tape. This
works identically for both backends and needs zero engine changes.

---

## 5. Phased delivery

Each phase is independently reviewable and mergeable. Phase 1 already removes
the documented limitation; later phases add the lazy/indexed/editing layers.

### Phase 1 — Eager multi-material parse/write  *(≈3 days)* — ✅ implemented

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
  emits the TPID once, each material body + its MEND, one final TEND. Each
  material is written with the unchanged engine `write()`; `write_tape` then
  strips the per-material TPID/TEND records from that output (post-processing,
  uniform across both backends — see Section 4).
* `include`/`exclude` accept today's MF / `(MF,MT)` tuples (apply to *all*
  materials) **and** `EndfMaterialPath` strings (`"9225#1/3"`) to scope per
  material. Tuple ambiguity (is `(9225,3)` MAT/MF or MF/MT?) is avoided by
  keeping tuples MAT-less and using the path string form for MAT scoping.
* `on_error`: `raise` aborts; `mark` keeps the failed material as a
  `FailedMaterial` object exposing `.exception` and `.raw_lines`.

Deliverable: README limitation note removed; `tests/test_multimaterial.py`
(23 tests, Python and C++ backends). **Done.**

### Phase 2 — Structural index  *(≈2 days)* — ✅ implemented

Goal: scan a tape into a recipe-free index without parsing section bodies.

* `TapeIndex.from_file(path)` / `TapeIndex.from_lines(lines)` — one linear
  pass, with the structural scan logic of `split_sections` (`endf_utils.py:459`)
  reimplemented standalone in `tape/index.py` (kept recipe-free; the existing
  `split_sections` is not touched). Per material records a `MaterialIndexEntry`:
  * `position` (0-based), `mat`, `za`, `awr` — `za`/`awr` from HEAD `C1`/`C2`
    (universal, recipe-free);
  * `byte_offset`, `byte_length` of the whole material;
  * `sections`: `{(mf, mt): SectionIndexEntry(offset, length, line_count)}`.
* Secondary maps: `mat -> [positions]`, `za -> [positions]`.
* Source-identity stamp: `(st_size, st_mtime_ns)` captured at scan time for
  optional staleness checks.
* The index is treated as read-only and is cheaply picklable (plain
  dataclasses plus a small wrapper class).

Deliverable: `tests/test_tape_index.py` (19 tests) — index structure vs. the
parser's section keys, byte offsets verified against a real file on disk,
`from_file`/`from_lines` agreement, PENDF-like repeated-MAT lookup, source
stamp, pickle round-trip. **Done.**

### Phase 3 — `EndfFile` lazy access + 3-tier cache  *(≈1 week)* — ✅ implemented

Goal: the stateful lazy class.

* `EndfFile(filename, *, parser=None, mode="index", parsed_cache_bytes=64<<20,
  raw_cache_bytes=64<<20, on_error="mark", verify_source=False)`.
  `parser` defaults to `EndfParserFactory.create(select="fastest")`.
  `mode` ∈ `{"index", "load_raw", "parse_all"}`.
* Mapping protocol over the extended address; `tape[i]` → `MaterialView`;
  `MaterialView[mf, mt]` → parsed section.
* Access path: Tier-2 parsed-section cache → Tier-1 raw cache → disk → parse
  via the engine. (The clean/dirty split and the dirty store arrive with the
  in-memory editing of Phase 5; in a read-only `EndfFile` every cached section
  is clean.)
* `cache.py` has two caches, both weighted by the section's raw-text byte size
  (free — from the index `SectionIndexEntry`): `_RawCache` (Tier 1, byte-budget
  LRU) and `_SectionCache` (Tier 2). `_SectionCache` keeps *strong* references
  only within its byte budget; an evicted entry stays weakly referenced, so a
  section the caller still holds keeps its identity if looked up again. (This
  replaces the draft's "skip externally-referenced entries during eviction":
  the cache's own strong reference would always defeat such a check — holding
  evicted entries weakly is the design that actually works.) A section larger
  than the whole budget is kept on its own.
* File access: **open/seek/read-span/close per section read** — no shared file
  handle, no shared seek position. A single coarse `threading.Lock` guards the
  cache mutation, making a shared `EndfFile` thread-safe (serialised).
* Picklability: `__getstate__` drops the lock and any handle, keeps
  path + config + index; `__setstate__` rebuilds. Lets an `EndfFile` (with its
  pre-built index) be sent to `ProcessPoolExecutor` workers.
* Convenience: `by_mat(mat, *, occurrence=None)` (raises `AmbiguousMaterialError`
  listing positions if needed), `by_za(za) -> list`, `find(*, mat=, za=) -> list`,
  `materials()`. (`failures()`/`ok()` from the draft are dropped: those suit the
  eager `parse_tape` result list — in a lazy `EndfFile` a parse failure surfaces
  per section, as a `FailedSection`, only when that section is accessed.)
* `__enter__`/`__exit__`; `unload(position=None)`; `MaterialView.__repr__` shows
  the MAT and ZA labels.

Deliverable: `tests/test_endf_file_lazy.py` (18 tests, Python and C++ backends)
— lazy access vs. the parser, eviction under a tight budget, weakref-pinned
identity, the preload modes, secondary lookups, the `on_error` policy,
`verify_source` staleness detection and a pickle round-trip. **Done.**

### Phase 4 — `EndfMaterialPath` query layer  *(≈3 days)* — ✅ implemented

Goal: semantic lookup decoupled from the engine.

* `EndfMaterialPath` (`address.py`) = a material selector + an unchanged
  `EndfPath`. `address.py` resolves `MAT`/`MAT#k`/`#k` against a `TapeIndex`
  → position. The structural prefix (`material/MF/MT`) is resolved by the
  index; the remaining suffix is walked on the recipe-parsed section with
  `EndfPath`'s own `get`/`exists`. `EndfPath` itself is not modified (D13).
* `EndfFile.get(path)` — `path` is an `EndfMaterialPath` (`material/MF/MT/...`);
  parses exactly that one section (cached in Tier 2) and returns the value.
  A section that fails to parse raises `SectionParseError` regardless of
  `on_error` — `get` is a point lookup, so failure is an error.
* `EndfFile.build_index(section_path, *, name=None)` — **explicit, opt-in**;
  takes a section-relative path (`MF/MT/...`, no material selector — it spans
  all materials), parses that section of every material and builds a secondary
  `{value -> [positions]}` map. Cost (1 section × N materials) documented.
* `EndfFile.query(section_path, value=…, *, predicate=…, tol=…)` — value or
  predicate match; numeric comparison takes a tolerance. Returns a list of
  `MaterialView`. Named `query` rather than the draft's `find` to avoid
  colliding with the Phase-3 structural `find(*, mat=, za=)`; `build_index` and
  `query` honour `on_error` (a failed section is skipped under `"mark"`).
* A curated set of common paths (`TEMP_ENDF`, `TEMP_PENDF`, …), so casual users
  need not know exact paths, is **deferred to a follow-up** — it would live in
  an isolated, opt-in `endf_parserpy/tape/common_paths.py`; semantic knowledge
  stays out of the engine.

Deliverable: `tests/test_tape_query.py` (15 tests, Python and C++ backends) —
`EndfMaterialPath` parsing/resolution, `get`, ambiguity handling,
`build_index`, and `query` by value/predicate/tolerance. **Done.**

### Phase 5 — In-memory structural editing & write-back  *(≈1 week)* — ✅ implemented

Goal: add/delete/reorder materials and sections, then write.

* Each material is a `_MaterialSlot` (`tape/material.py`) carrying an *edit
  overlay*: `overlay` holds set/added sections keyed by `(MF, MT)`, `deleted`
  the removed keys. `EndfFile` keeps an ordered list of slots — Phases 3–4
  (`EndfFile`/`MaterialView`) were refactored onto this slot model. Editing is
  done through that list and the overlays; the draft's `MutableMapping`
  interception is unnecessary because nothing needs to *distinguish* structural
  from value edits — the index stays valid for either (next point), so an edit
  is just an overlay entry. `MaterialView.is_modified` reports whether a slot
  has any overlay/deletion.
* The index stays valid throughout: it is immutable and refers to the
  *original* file. In-memory add/delete/reorder never moves on-disk bytes, and
  each slot keeps a stable `original_position` into the index. New materials
  have no `original_position` (all their sections live in the overlay).
* `MaterialView` is bound to its slot, not to a position, so it survives a
  reorder; it becomes invalid only if its material is deleted.
* Editing API: `material[mf, mt] = section` / `del material[mf, mt]`;
  `del endf_file[i]`, `endf_file.append_material(material, mat=…)`,
  `endf_file.reorder(order)`.
* `EndfFile.save(out=None, *, overwrite=False)` assembles each material into a
  `{MF: {MT: section}}` dict (untouched sections taken verbatim from disk,
  edited/added ones from the overlay) and writes via `write_tape`. Untouched
  sections round-trip byte-exact. Writing to a path goes through a temporary
  file + atomic `os.replace`, so saving back onto the source file is safe.

Deliverable: `tests/test_tape_editing.py` (14 tests, Python and C++ backends) —
unedited byte-exact save, value edits, section add/delete, material
delete/append/reorder, same-path save, view identity through reorder, and a
pickle round-trip that preserves edits. **Done.**

*Deferred to a follow-up:* automatic regeneration of the MF1/MT451 directory
(`NC` counts) after edits — `save` currently leaves the directory as-is, so a
material whose section set changed should have `update_directory` applied. Also
deferred: streaming the write (`save` assembles all materials before writing).

---

## 6. Round-trip contract

* A raw-kept MT section (parsed with `exclude`, or no recipe available, or never
  accessed in lazy mode) → its **data records are copied verbatim**, so every
  data field is preserved byte-for-byte.
* A parsed/dirty MT section → canonical re-render via the recipe + `write_opts`.
* The SEND/FEND/MEND framing records and the column 76-80 sequence numbers are
  regenerated for every section either way, so the framing is conformant but
  not necessarily a byte-copy of the input.
* Line endings normalised to LF; inter-material blank lines dropped.
* Therefore: a tape parsed with `exclude=(everything)` and written back
  reproduces every data field byte-for-byte, but is **not** byte-identical
  overall — the framing and sequence numbers are re-emitted. This data-exact
  round trip is the basis of the strongest round-trip test.

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
* **Round-trip suite:** parse-with-full-exclude → `write_tape` → assert every
  data field is preserved byte-for-byte (framing and sequence numbers are
  regenerated) on a multi-material fixture.
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
| Source file changed under a long-lived `EndfFile` | opt-in `verify_source` re-stats `(size,mtime)`; raises `StaleSourceError` |

---

## 10. Effort estimate

| Phase | Estimate |
|-------|----------|
| 1 — eager multi-material | ~3 days |
| 2 — structural index | ~2 days |
| 3 — lazy `EndfFile` + cache | ~1 week |
| 4 — `EndfMaterialPath` query layer | ~3 days |
| 5 — structural editing + write-back | ~1 week |
| docs, examples, CI polish | ~3 days |
| **Total** | **~4–5 weeks** |

Phases 1–2 are low-risk and independently shippable. Phases 3–5 are additive —
a new class layered over an unchanged engine — so risk to existing behaviour is
near zero throughout.

---

## 11. Resolved review items

All open items from the design review are settled:

1. Module location → `endf_parserpy/tape/`.
2. `iter_parse_tape` yields **bare dicts** (and a `FailedMaterial` object for
   failures), mirroring the existing `parse`/`parsefile` return semantics.
3. Public class name → **`EndfFile`** (no legacy "tape" jargon in the user-
   facing class; the `tape/` module keeps the term internally).
4. Path type → **`EndfMaterialPath`**, a new type composing an unchanged
   `EndfPath` (D13).
5. `common_paths.py` → **deferred** to a follow-up.

---

## 12. Future direction (non-goal for v1)

A natural next layer is a cross-file aggregator — provisionally **`EndfLibrary`**
— presenting many ENDF files (single- or multi-material) under one addressable,
editable namespace, abstracting away file boundaries. It is the same
compositional pattern applied one level up:
`EndfLibrary` → `EndfFile` → `MaterialView` → `(MF,MT)` section.

This is **explicitly out of scope for v1**, but the v1 design must not preclude
it — and does not:

* `EndfMaterialPath` would gain an optional leading *file / library-member*
  component; the `MAT` / `#k` grammar is unaffected.
* `EndfFile` stays a self-contained unit the aggregator simply composes, exactly
  as `EndfFile` composes per-material units.
* The index/cache machinery generalises — a library index is a union of
  per-file indexes plus a file dimension.

The name `EndfTape` is deliberately **not** used for this aggregator: in ENDF
terminology a *tape* is canonically a single file (the unit ended by TEND), so
`EndfTape` would be both inaccurate for a cross-file object and a reintroduction
of the jargon dropped from `EndfFile`.
