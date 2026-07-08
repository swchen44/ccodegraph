# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Pre-1.0 caveat (SemVer §4): anything MAY change at any time; the public API
(schema contract, CLI verbs) should not be considered stable until 1.0.0.

## [Unreleased]

### Added

- **D16 explicit output truncation**: `callers`/`callees`/`explore` cap each
  section at 40 rows by default; `sql` caps at 200 rows. New `--limit N` flag
  overrides both (`0` = unlimited). Truncation is always explicit — the tail
  line and `explore` section headers report the TRUE total, and `--json`
  carries `total`/`truncated` fields — so enumeration answers stay correct
  while a pathological-fan-in `callers` drops from ~28KB to ~2KB (v3 benchmark
  token-hotspot finding, WRQ-005).
  **v4 benchmark acceptance (same 22 questions, Sonnet 5, codex-judged): score
  58/66 -> 62/66, total cost -3%, cost per correctness point -9.4%, startup
  ritual (--help/schema/status) eliminated entirely; full before/after report
  in docs/research/llm-ab-v4-token-efficiency.md.**

### Changed

- SKILL.md rewritten for token efficiency (13.1KB → 6.1KB): full command
  cheatsheet with exact syntax (kills `--help` lookups), embedded DB schema
  (kills the `schema`-first ritual), a measured token-discipline section
  (scope queries in SQL, narrow Reads at cited file:line, COUNT cross-check
  before claiming totals), trust-calibration and blind-spot guidance kept but
  compressed. Driven by the v3 benchmark where ccodegraph was the most
  expensive arm per correctness point (see
  docs/research/llm-ab-v4-token-efficiency.md).

## [0.0.4] - 2026-07-07

### Added

- `status` v3 as a support-triage tool (codex round-4 review adopted):
  `health: OK|WARN|ERROR` headline + stable `issues[]` codes with actions
  (ENV_UNKNOWN_VARS typo detection, STALE_GRAPH, ROOT_MISMATCH, SKILL_STALE,
  CLINK_SYNTHESIZED, TOOL_MISSING…), `status_schema_version` for automation,
  tool ✓/✗ + ctags flavor, DB identity checks (recorded root / git),
  clink last-import stats, compile-DB entry count; noisy details moved to
  `--full` (all env vars, per-file products, full drift list, history×5).
- SKILL.md embedded in ccodegraph.py (base64 block via `tools/embed_skill.py`)
  so a standalone file can emit it; unit test enforces embedded == file.
- Hard-case benchmark v2 (`docs/research/llm-ab-v2-hard-cases.md`): a
  22-question harder test bank (`docs/research/hard-benchmark/`, adapted
  from a 12-category/L1–L4 Linux-kernel navigation taxonomy) for
  wpa_supplicant/redis; 4 of the hardest questions run for real via
  Claude Code headless mode (Arm A: grep-only vs Arm B: ccodegraph),
  plus an Arm C 3-way comparison using a real `bear`-generated
  `compile_commands.json` for 2 redis cases. Honest result: on these
  harder questions the two arms land near-parity on correctness; the
  real differentiators are precision on summary arithmetic, proactive
  risk-flagging of fn-pointer dispatch, and fewer tool calls per answer
  — not "can answer at all vs can't."

### Fixed

- **D15**: cscope reporting an internal error for a single symbol that is
  referenced extremely densely within one file (e.g. vendored macros like
  jemalloc's `CTL`) no longer aborts the whole `build` — that symbol's
  query is skipped with a warning (recorded in `history.cscope_skipped`),
  and the rest of the graph still builds. Found while building a real
  benchmark graph on redis; verified no edge-count regression on wpa.

## [0.0.3] - 2026-07-06

### Added

- Multi-DB advanced workflow: `--db` documented as a universal parameter for
  per-compile-config graphs; clink by-products now follow the graph name
  (`cfgA.db` → `cfgA.clink.db`); `meta.db_label` + append-only `meta.history`
  (every write logged); new `dumpdb` verb (the DB's identity card); `status`
  lists all databases under `.ccodegraph/`.
- R8 `--module-map module_mapping.csv` (col 1 regex — case-insensitive for
  ASCII, col 2 module name incl. Unicode; first match wins; bad rows fail
  loudly) fills `nodes.module`; `viz` colors nodes by module.
- README restructured into User zone / Developer zone with flow diagrams and
  command categories; full English translation (`README.en.md`).
- SKILL: "this file is the complete reference" + verify-only-when-answer-
  critical guidance (real-LLM A/B finding: self-verification was the main
  token overhead of the tool arm).

## [0.0.2] - 2026-07-06

### Fixed

- cscope index file now really lands in `.ccodegraph/cscope.out` (the rename
  had silently no-opped; legacy root `.ideal-graph.cscope.out` auto-removed).
- macOS `/var` ↔ `/private/var` symlink duality broke synthesized compile-DB
  lookups (clink silently fell back to fuzzy parsing) and produced garbage
  relative paths in imported sites — all paths now realpath-canonicalized.
- Incremental builds force a full cscope cross-reference rebuild (`-u`):
  cscope's own mtime check has 1-second granularity and missed rapid edits.
- Test-runner discipline: Python 3.13 colorized unittest output defeated the
  CI-parity grep locally; suites now run with NO_COLOR and are judged by
  exit code.

### Changed

- **D14 (honest correction)**: `semantic: absent` documented as a
  parse-coverage flag ("clink never successfully looked here"), NOT an
  inactive-`#ifdef` indicator — clink's call extraction is token-level and
  includes inactive regions by design. SKILL risk chapter, README and design
  docs updated; fixture pins the corrected reality.

## [0.0.1] - 2026-07-06

First public release. C/C++ knowledge graph for LLM agents: zero-build
indexing, multi-engine fill, every row labelled with origin + confidence.

### Added

- **Schema contract v2** (`docs/design.md` §1.5): `nodes` (function | global |
  macro | file, with qname disambiguation, signature, `module` column reserved
  for module_mapping) / `edges` (calls | callback | fnptr | reads | writes |
  includes | expands | co_changes, one row per call site, `origin` +
  `confidence` + `meta` tags on every row) / `edge_pairs`, `file_deps` views.
- **Layered fill engines** (each independently re-runnable):
  - L0 `ctags` nodes (qname rules: static → `file::name`, non-static dups
    qualified, same-file `#ifdef` dups get `:line` suffix; signatures via `+S`).
  - L1 `cscope` edges: calls (via `-dL3` inversion), reads/writes (with
    read-modify-write compensation — cscope misses `x++` as a write),
    includes (spelling-variant matching against dup basenames).
  - L2′ macro dimension: macro nodes + `expands` edges.
  - L3 heuristics: callback (fn-as-argument) + fnptr (field-keyed dispatch)
    + user manual table `fnptr.json` (registrations + links,
    asserted_by_user semantics, sha256 stale detection).
  - L4 semantic layer via `clink`/libclang (optional): `clink-import` verb,
    compile-DB ladder (`--compdb a,b,c` file-level merge with first-wins and
    per-conflict reporting → auto-detect → synthesized no-build DB),
    per-edge `semantic: confirmed|absent` annotation, incremental by re-run.
  - L5 git layer: sha256 incremental rebuild (`build --incremental`,
    1-file change ≈ 4 s on a 620-file repo, normalized diff = 0 vs full
    rebuild) + `co_changes` edges from commit history.
- **Query verbs**, all with `--json` (fields 1:1 with text): `schema`
  (introspection first), `explore`, `callers`/`callees` (per-definition
  sections), `impact` (CodeGraph-shaped: "affects N symbols" + by-file
  groups, depth default 2 clamp 1–10), `globals`, `vars-of`, `who-includes`,
  `co-changed`, read-only `sql` escape hatch.
- **`viz`**: single offline interactive 2D/3D HTML (vendored force-graph /
  3d-force-graph, MIT), call-family by default, `--full` for all 8 edge
  kinds, `--focus X -d N` BFS, kind filters / search / degree / max-nodes.
- **Maintenance**: `status` (tools + env-override flags, skill detection,
  products with sizes, artifact provenance, hash-exact drift list),
  `reset`, `skill` (prints embedded SKILL.md for air-gapped installs).
- **Agent SKILL.md** with a RISK CHAPTER: how every confidence level fails,
  `semantic:absent` = config-gated not false, ambiguous candidates,
  origins-agreement scoping, error → next-step table.
- Tool path env vars: `CCODEGRAPH_{CTAGS,CSCOPE,CLINK,GIT}_PATH`.
- Universal Ctags flavor gate with per-platform install guidance; CI matrix
  (ubuntu / macos / windows).
- Tests: 124 (unit / integration / e2e, stdlib unittest); ruff + mypy
  --strict gates.

### Measured (wpa_supplicant, 620 files; methodology in `docs/`)

- Call-edge recall 28/28 vs cflow GT (cscope alone 26/28); fnptr 5/5;
  callback 3/3; incremental 3.9 s; real-LLM A/B: correctness 5/5 vs 3/5
  against a grep-only agent (details in `docs/research/llm-ab.md`).

[Unreleased]: https://github.com/swchen44/ccodegraph/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/swchen44/ccodegraph/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/swchen44/ccodegraph/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/swchen44/ccodegraph/releases/tag/v0.0.1
