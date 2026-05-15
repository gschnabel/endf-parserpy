# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Multi-material ENDF tape support via the new functions `parse_tape`, `iter_parse_tape` and `write_tape`. These parse and write ENDF files that contain several materials, including PENDF/GENDF tapes that repeat the same material at different temperatures. A tape is split lexically into single-material chunks that are handed to the ordinary single-material parser, which is used unchanged. `iter_parse_tape` streams one material at a time so peak memory stays bounded by the largest single material. The `on_error` option (`"raise"` or `"mark"`) selects whether a material that fails to parse aborts the operation or is returned as a `FailedMaterial` (which round-trips verbatim through `write_tape`). This removes the long-standing limitation that only a single material per file was supported
- `TapeIndex`: a structural index over the materials of an ENDF tape, built with `TapeIndex.from_file()` or `TapeIndex.from_lines()`. A single linear scan records, for every material, its MAT number, the ZA/AWR identifiers, the byte range it occupies and the byte range of every (MF, MT) section. The scan is recipe-free (it inspects only the MAT/MF/MT control fields and the universal HEAD-record layout) and therefore independent of the parsing engine. Materials are addressed by zero-based position; `by_mat()` and `by_za()` provide secondary lookups that return all matching positions (PENDF tapes repeat a MAT number). The index is picklable and records the source file size and mtime for staleness checks

## [0.16.1]

### Changed

- C++ extension build time reduced by roughly 5x on multi-core machines (measured: 6:44 → 1:18 on a 4-physical / 8-logical i7-1165G7) by combining three changes: (a) parallel compilation across the six flavor extensions, (b) hash-based deduplication of recipe-derived parse/write functions so identical functions across flavors are now emitted once into a shared translation unit, and (c) splitting that shared translation unit into N pieces so it itself compiles in parallel. Mitigates the long install times observed by downstream CI users (#42)
- Two new environment variables control the build parallelism: `INSTALL_ENDF_PARSERPY_NUM_BUILD_JOBS` (worker count, default `os.cpu_count()`) and `INSTALL_ENDF_PARSERPY_NUM_SHARED_CHUNKS` (number of shared-TU chunks, default `min(os.cpu_count(), 8)`)

### Fixed

- Docstring of `EndfParserCpp` now documents the `validate_control_records` parameter

## [0.16.0]

### Added

- ENDF recipe for MF26 (electroatomic interaction data)
- ENDF recipe for MF28 (atomic relaxation data)
- ENDF recipe for MF30/MT1 (directory of model-parameter covariances) and MF30/MT2 (covariance matrix)
- `accept_nan_inf` option on `EndfParserPy` and `EndfParserCpp` (default `True`): allow non-finite floats (`NaN`, `+inf`, `-inf`) in ENDF fields; with `False` such values raise. The writer also gained the ability to emit non-finite floats as the textual tokens `NaN` / `Inf` / `-Inf` right-aligned in the 11-character field
- Optional `defaults` parameter on `add_common_cmd_parser_args` to override argparse-level defaults for individual subcommands and surface those overrides in `--help`

### Fixed

- C++ parser: number parsing now uses `std::strtod` instead of `std::stod`, which avoids spurious exceptions on subnormal values produced by some evaluations (770 affected files in JEFF-4.0/tsl)
- C++ parser: `cpp_read_vec` no longer consumes a line when `numel == 0`, fixing 59 spurious SEND-record failures in TENDL-2025/he3 metastables
- C++ codegen: the `?` (inconsistent variable) marker is now propagated through `:=` placeholder expansions, so recipes like `NX := ...; NX?` are honored under `ignore_varspec_mismatch=True`. This unblocks parsing of JEFF-4.0/n Gd-155, Gd-157 and O-16 with the C++ parser (#53, #55)
- `endf-cli validate`: strict defaults are now reflected at argparse level and shown in `--help`; an `accept_nan_inf=False` strict default was added so non-finite floats are rejected by default during validation; an override-after-parse code path was retired as redundant (#56)
- C++ parser: SEND/FEND/MEND/TEND completeness is now checked at EOF. Tapes truncated before MEND/TEND no longer parse silently; this matches the long-standing Python behavior (#57)
- C++ parser: integer-field parsing is now strict. `std::atoi`-based silent truncation of float-shaped strings (`"0.000000+0" -> 0`, `"4.000000-6" -> 4`, etc.) has been replaced with a `std::strtol`-based path that rejects anything Python's `int()` would reject. A blank field still reads as zero per ENDF convention (#58)

### Changed

- `endf-cli validate` is now strict-by-default across `ignore_number_mismatch`, `ignore_zero_mismatch`, `ignore_varspec_mismatch`, `accept_spaces`, `ignore_blank_lines`, `ignore_send_records`, `ignore_missing_tpid`, and `accept_nan_inf`. Each flag can still be overridden individually on the command line
- C++ parser is stricter by default in two ways that previously masked malformed files: it now rejects tapes truncated before MEND/TEND, and it now rejects float-shaped strings in integer fields. Both behaviors match the Python parser. Files that relied on the old silent acceptance can opt back in with `ignore_send_records=True` and, for integer fields, must be repaired (no opt-in flag is provided)

## [0.15.0]

### Added

- Adler-Adler formalism in MF2/MT151 ENDF recipe (#43)
- Comprehensive description in MF2/MT151 and MF32 recipe (#43 and #45)

### Fixed

- Some edge cases in the MF2/MT151 and MF32 recipe (#43)
- Issue with `endf-cli match` command for variable names with underscore (#49)
- Issue with `ignore_blank_lines` option of C++ parser (#51)

### Changed

- Consistent names in MF2/MT151 and MF32/MT151 ENDF recipes
- Default C++ optimization level for faster package installation (#52)
- GitHub workflow to enable native compilation on ARM architecture

## [0.14.3]

### Deprecated

- The `EndfParser` class has been renamed to `EndfParserPy` and the old name should not be used anymore

### Added

- Support of `repat...until` syntax in formal recipe language
- Support of `stop` instruction to C++ parser generator
- `EndfParserFactory` class for automatic selection between Python and C++ parser
- Abstract base class `EndfParserBase` serving as parent class for `EndfParserCpp` and `EndfParserPy`
- Recipe flavor ``errorr`` to support parsing and writing NJOY ERRORR output files
- Support of array values as indices in ENDF recipes
- Possibility to control C++ optimization level via `INSTALL_ENDF_PARSERPY_CPP_OPTIM` environment variable
- Tests to verify character by character equivalence of Python and C++ parser output

### Fixed

- Python parser now always inject MAT, MF, MT numbers before parsing
- Inject MF, MT if missing before writing via `EndfParserCpp`
- Deal gracefully with `UnavailableIndexError` in if-lookahead
- Ensure character by character equivalence of `EndfParserPy` and `EndfParserCpp` output
- C++ parser now accepts blank lines after TEND record (irrespective of `ignore_blank_lines` option)
- Division-by-zero issue in arithmetic expressions generated by C++ parser code generator

### Changed

- Replaced deprecated dependency `appdirs` by `platformdirs` package
- Default value of `fuzzy_matching` Python parser argument to `False`
- Expose `include_linenum` argument in command-line interface
- Disabled zero padding of list bodies in Python parser (same behavior now as C++ parser)
- Interaction with `importlib.resources` API to avoid deprecation warnings

## [0.13.1]

### Fixed

- Enable conversion from Python `int` to `EndfFloatCpp` object in C++ code

### Changed

- More descriptive error message for blank line error in generated C++ parser code

## [0.13.0]

### Added

- Conversion between ENDF and JSON format via command-line interface

### Fixed

- ENDF recipe for MF1/MT460
- `EndfParser` `write` method to deal with `EndfDict` object as input
- Some mistakes in the documentation
- Invalid escape sequence in doc string (#10)

## [0.12.0]

### Added

- `EndfFloat` class for storing float numbers with associated original string
- Support of PENDF files produced by NJOY
- Argument `preserve_value_strings` to `EndfParser` and `EndfParserCpp` class
- `matching` module for matching ENDF files according to logical expressions
- Argument `array_type` to `EndfParser` and `EndfParserCpp` to support representing ENDF arrays as Python `list`

### Removed

- Option `blank\_as\_zero` from `EndfParser` constructor---now blank numeric fields are always interpreted as zero.

### Fixed

- SEND record treatment in cpp parser for sections read verbatim
- `EndfParserCpp` on Windows 11 by using binary mode for reading/writing
- Output of integers instead of float numbers in SEND records
- Avoid check of MAT/MF/MT consistency if `ignore_send_records` option is active
- Add forgotten newline character while joining list of strings in `EndfParserCpp.parse` method.
- Do not remove last line when writing verbatim MF/MT section with `EndfParser`

### Changed

- Options for reading and writing are now passed as dictionaries (`read_opts` and `write_opts`) to functions.
- Redesigned and extended command-line interface

## [0.11.0]

### Added

- Argument `include_linenum` to `EndfParser` class constructor [#6](https://github.com/IAEA-NDS/endf-parserpy/issues/6)
- Argument `include_linenum` to `EndfParserCpp` and C++ parsers [#6](https://github.com/IAEA-NDS/endf-parserpy/issues/6)
- Variable `__version__` in package namespace [#5](https://github.com/IAEA-NDS/endf-parserpy/issues/5)

### Fixed

- Sequence number is reset to 1 if it exceeds 99999 [#6](https://github.com/IAEA-NDS/endf-parserpy/issues/6)

## [0.10.3]

### Added

- First version for reference in this changelog
