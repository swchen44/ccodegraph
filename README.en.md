**English** · [繁體中文](README.md)

# ccodegraph — C/C++ knowledge graph (C-first, multi-engine, provenance-labelled)

A C/C++ code knowledge graph built for LLM agents: **zero-build** indexing
(ctags + cscope + heuristics), optional semantic layer (clink/libclang) and a
git layer, all filled into one SQLite database — every row stamped with
`origin` + `confidence` + tags. **Judgement is left to the LLM; uncertain data
is labelled, never deleted.**

---

# User zone

## Quick start (three minutes)

```bash
# deps: python3 (stdlib only), universal-ctags, cscope; optional: clink, git
./ccodegraph.py build -p <repo>              # step 1: build the graph (no build system needed, ~3s / 600 files; 7.6k-file kernel subtree ~22s)
./ccodegraph.py clink-import -p <repo>       # step 2 (optional): semantic layer
./ccodegraph.py explore some_function -p <repo>   # start asking!
```

```mermaid
flowchart LR
    B["build<br/>(text layers, required)"] --> C["clink-import<br/>(semantic, optional)"]
    C --> Q["query verbs<br/>explore / callers / impact / …"]
    Q -->|code changed| I["build --incremental<br/>(~4s) → clink-import again"]
    I --> Q
    Q -->|done| R["viz export / reset"]
```

## Command categories

**Build (basic)**

| Command | Purpose |
|---|---|
| `build -p <repo>` | build the graph → `.ccodegraph/graph.db`; after edits add `--incremental` (1-file change ≈ 4 s, provably equal to a full rebuild) |
| `clink-import -p <repo>` | optional semantic layer; **re-running IS incremental** (clink keeps per-file hashes); compile-DB ladder: `--compdb` merge → auto-detect → synthesize |

**Query (basic; every verb supports `--json` — the LLM picks the format)**

| Command | When |
|---|---|
| `explore X` | first move: definition + callers + callees + globals touched, one shot |
| `callers X` / `callees X` | who calls / what it calls (incl. fnptr/callback indirection and macro users) |
| `impact X -d N` | blast radius: "affects N symbols" + by-file groups (depth default 2) |
| `globals V` / `vars-of F` | who reads/WRITES a global / which globals F touches |
| `who-includes H` / `co-changed F` | header impact / git co-change |
| `viz [--format html2d\|html3d] [--focus X]` | offline interactive graph → `.ccodegraph/graph-<dim>.html` |

**Maintenance**

| Command | Purpose |
|---|---|
| `status` | health check: tool versions & paths, product sizes, database list, **drift list vs the source tree** |
| `dumpdb` | the DB's identity card: label, schema, **append-only write history**, per-layer stats |
| `schema` | the graph's self-introduction: which slots are filled, by whom, STALE warnings |
| `reset` | delete everything under `.ccodegraph/` (prints each removal) |
| `skill` | print the agent SKILL.md (air-gapped install: `skill > ~/.claude/skills/ccodegraph/SKILL.md`) |

## Routine maintenance flow

```mermaid
flowchart TD
    S["status"] -->|aligned| OK["just query"]
    S -->|"N file(s) differ"| INC["build --incremental"] --> CL["clink-import"] --> OK
    S -->|"STALE (fnptr.json changed)"| INC
    OK -->|suspicious answer| V["open the cited file:line<br/>or re-check via sql"]
```

## Advanced

### Multiple compile_commands.json (one source tree, several targets)

```bash
./ccodegraph.py clink-import --compdb build1.json,build2.json,build3.json -p <repo>
```
File-level merge: for a shared file the **first** DB listing it wins (order =
priority); target-exclusive files are all kept; genuine rule conflicts are
reported one by one. **Limitation (first-wins)**: a file's alternative-config
semantics are invisible to the semantic layer once merged.

### One graph per config (when first-wins isn't enough)

`--db` is a universal parameter on every verb. Text layers are identical
across graphs; only the semantic layer differs by compile DB:

```bash
./ccodegraph.py build -p <repo> --db .ccodegraph/cfgA.db
./ccodegraph.py clink-import -p <repo> --db .ccodegraph/cfgA.db --compdb buildA.json
./ccodegraph.py callers foo -p <repo> --db .ccodegraph/cfgA.db
```
clink by-products follow the graph name (`cfgA.clink.db`) so configs don't
stomp each other. **Keep custom DBs under `.ccodegraph/`** (as above): `status`
lists them and `reset` cleans them; anywhere else works too, but is outside
status/reset reach — your path, your responsibility.

### Module grouping (module_mapping.csv)

```bash
# module_mapping.csv: col 1 = regex (matched against file paths,
# case-insensitive), col 2 = module name (Unicode welcome)
#   ^src/utils/,utils-layer
#   ^src/drivers/,drivers
./ccodegraph.py build -p <repo> --module-map module_mapping.csv
./ccodegraph.py viz -p <repo>        # same module, same color
```

### Tool paths

`CCODEGRAPH_{CTAGS,CSCOPE,CLINK,GIT}_PATH` env vars override the system PATH
lookup. (No libclang variable — it is linked into clink at its build time.)

## Installing the agent skill

```bash
mkdir -p ~/.claude/skills/ccodegraph
./ccodegraph.py skill > ~/.claude/skills/ccodegraph/SKILL.md   # method 1 (air-gapped friendly)
cp skills/ccodegraph/SKILL.md ~/.claude/skills/ccodegraph/     # method 2
```
The SKILL's core is its **RISK CHAPTER**: how each confidence level fails,
what `semantic:absent` really means (a parse-coverage flag, D14), ambiguous
candidates, STALE handling.

## Measured numbers (wpa_supplicant, 620 files; methodology in docs/)

| Metric | Value |
|---|---|
| Call-edge recall (28-edge cflow GT) | **28/28** (cscope alone 26) |
| fnptr dispatch / callback | 5/5 / 3/3 |
| build / incremental / no-op | **3.4 s** (90 s pre-D17) / 3.9 s / 3.8 s (incremental == full, normalized diff = 0, endpoint kinds included) |
| Real-LLM A/B (codex, 5 tasks) | tokens roughly even; **correctness 5/5 vs 3/5** (grep arm silently wrong twice) |

### Measured at scale (after the D17 crossref direct read, 2026-07-11; `/usr/bin/time -l`)

| repo | files | build | graph size |
|---|---|---|---|
| wpa_supplicant | 620 | 3.4 s | 14.4k nodes / 113k edges |
| redis (deps/ included) | 784 | 4.1 s | 20.1k nodes / 146k edges |
| Linux kernel subtree | 7,627 | **22.5 s** (median of 3; 3h15m pre-D17 = **521×**) | 427k nodes / 339k edges |
| Linux kernel full tree | 56,939 | **62 min** (pre-D17: killed unfinished at 14.5 h, 30-40 h extrapolated) | 6.2M nodes / 54.9M edges / 16 GB |

D17 = parse cscope.out directly (one pass replaces per-symbol queries); it
also fixed three classes of phantom bugs in cscope's own `-L` query engine —
engineering record in `docs/design.md` §8.5.6, bug evidence in
`docs/research/cscope-query-engine-bugs.md` (filed upstream:
[cscope #306](https://sourceforge.net/p/cscope/bugs/306/)), the four-tool
kernel shootout in `docs/research/llm-ab-v5-linux-kernel.md` (§4.1 is the
post-D17 addendum). Open problem at full-tree scale: same-name ambiguous
attachment (D3) explodes edge counts at 57k files (reads alone: 28.3M).

### Six rounds of LLM benchmarks at a glance (2026-07; methodology: `docs/research/benchmark-methodology.md`)

Every round: isolated clean trees, frozen prompts, independent grading
against pre-verified ground truth; all raw run/grade JSONs archived.
**Negative results published as-is.**

| round | arena | arms | result | report |
|---|---|---|---|---|
| v1 | wpa, 5 tasks (N=1) | ccodegraph vs bare grep | correctness **5/5 vs 3/5** (grep silently wrong twice), tokens even | `llm-ab.md` |
| v3 | wpa+redis, 22 questions (N=1) | grep/ccodegraph/CodeGraph/cbm | 54/**58**/58/57 (/66) — graph tools directionally ahead, but ccodegraph costliest per point | `llm-ab-v3-full-suite.md` |
| v4 | same, after teaching-layer rework | ccodegraph rerun | **58→62** at **-9.4%** cost per point — the gain is all teaching layer | `llm-ab-v4-token-efficiency.md` |
| v5 | **Linux kernel** subtree, 7.6k files, 20 questions (N=3) | same four arms | QA near-tie: 58/59/**60**/59 (/60, codegraph on top); **indexing is the real gate**: on the full 57k-file tree only ccodegraph finished (62 min) — cbm crashed, codegraph OOM'd | `llm-ab-v5-linux-kernel.md` |
| v6 | wpa+redis, 22 questions (N=3) | grep/clangd LSP/ccodegraph (+ tuned-LSP arm) | table below | `llm-ab-v6-lsp.md` |
| v7 | wpa+redis, 8 **edit tasks** (N=3, compiler-judged) | grep/lsp-on/lsp-off/ccodegraph | **all four arms 24/24, dead tie** — diagnostics=make (the agent's native workflow carries its own feedback loop); LSP queries nearly extinct in edit tasks (5 calls/96 runs) | `llm-ab-v7-edit-loop.md` |

**v6: the LSP shootout** (external suggestion "LSP + compile DB works
well too" → controlled test):

| arm | score /66 | cost per point |
|---|---|---|
| plain grep/read | 60 | $0.290 |
| clangd LSP plugin (out of box) | 60 | $0.336 |
| LSP + a SKILL-level teaching layer (66-run follow-up) | 61 | $0.431 |
| **ccodegraph** | **63** | $0.347 |

v6 key findings: ① **tool presence ≠ tool usage** — with the prompt
saying "prefer LSP", 36% of runs never invoked it once (342 Bash calls
vs 117 LSP calls); ② a one-line "prefer LSP" hint measurably does
nothing (9-run probe), while a full teaching skill made usage more
*precise* (call-hierarchy ops 5→26) yet bought exactly +1 point;
③ clangd's `findReferences` can be **silently incomplete** (a measured
case of 4 returned out of hundreds, no warning) — always cross-check
counts.

### Glossary (benchmark-series jargon, with examples)

| term | origin | meaning | example |
|---|---|---|---|
| **arm** | clinical trials | one tool configuration in the benchmark; arms compete on identical questions/conditions | "36% of lsp-arm runs never called LSP once" |
| **GT** (ground truth) | ML/evaluation | the pre-verified correct answer (one `gt_WRQ-XXX.md` per question) that the grader scores 0-3 against | "GT counts 70 includers; the agent said 66 → scored 0" |
| **oracle** | software testing | the authority you judge outputs against; "verify your oracle" = the judge itself can be wrong | "differential-testing our parser against cscope-as-oracle ended up convicting the oracle" |
| **dual-gating** | coined here (v4) | config-dependent code has TWO switches: in-file `#ifdef` AND the build system (Makefile `OBJS +=`/Kconfig); checking one layer misses whole files | "WRQ-013 is a dual-gating question: sae.c is gated by the Makefile, invisible to `#ifdef` grep" |
| **spike** | agile | a timeboxed feasibility experiment with acceptance numbers fixed up front; discard on failure | "the D17 spike: Day 1's hypothesis was refuted, fell through to the planned Day 2" |
| **DNF** (did not finish) | motorsport | indexing that never completed (timeout/crash/OOM), honestly recorded as such | "cbm DNF'd the full tree: crashed at a 26GB footprint" |
| **zero regression** | software testing | no quality loss whatsoever after a change; "edge-count zero regression" = old/new graphs diffed edge-by-edge, every vanished edge must be proven an old-engine error | "D17's red line — the -q variant died on it" |
| **wall** (wall-clock) | systems perf | real elapsed time (what you waited), vs user/sys CPU time; the gap = waiting on I/O | "full tree: 62 min wall but only ~10 min user — the disk is the story" |
| **N=3 / rep** | statistics | each cell runs three times (reps 1/2/3), median taken, to kill single-draw luck | "WRQ-019 scored 3 in the N=1 smoke, median 2 at N=3" |
| **smoke** | software testing | a small pre-flight run to validate the pipeline/behavior; never counted in conclusions | "2-question smoke to confirm the LSP arm actually uses the tool, then the 198-run batch" |
| **phantom** | coined here (D17) | a site a tool reports where the source line does not contain the symbol at all | "all 92 vanished sites machine-verified as cscope query-engine phantoms" |
| **differential testing** | software testing | feed two independent implementations the same input and diff outputs row-by-row; every mismatch convicts one side | "3,400 queries diffed parser-vs-cscope; the residue exposed three oracle bug classes" |
| **same-venue / cross-venue** | house usage | only arms rerun together under identical conditions compare directly; cross-venue scores show trends only (models/envs drift) | "the none arm drifted 54→60 from v3 to v6, so v6 concludes from same-venue arms only" |
| **frozen** | experimental design | prompts/conditions locked after smoke; zero edits during the full run, changes only in smoke and on the record | "the LSP prompt froze after smoke; the tuned arm added only a SKILL file, prompt untouched" |
| **headless** | software eng. | non-interactive batch mode (`claude -p`); all benchmark runs execute this way for condition parity | "198 headless runs, each in a fresh isolated tree" |
| **turns** | agent domain | the agent's think-then-call-tool round trips; task time ≈ turns × model latency | "the indexer arm used fewer turns (9 vs 16) and spent the savings on verification" |

The through-line across rounds: **the teaching layer sets a tool's
ceiling** (same discipline: ccodegraph +4, clangd +1, a one-liner +0 —
`teaching-layer-methodology.md`); **scale is the real divide**
(disciplined grep nearly matches everything on medium repos; kernel-
scale index feasibility and macro/multi-config enumeration are where
structured tools genuinely differ). Scope: C × read-only navigation;
the edit loop (diagnostics) is LSP's home turf, untested. External
evidence reconciliation: `docs/research/lsp-external-evidence.md`.

---

# Developer zone

## Required reading (in order)

1. [docs/requirement.md](docs/requirement.md) — **Why (W1–W7) and What**: the rationale behind every trade-off; first file for handover
2. [docs/design.md](docs/design.md) — **How**: Schema Contract (§1.5, every legal value enumerated), decision records **D1–D17** (including overturned ones and why), roadmap
3. [docs/traceability.md](docs/traceability.md) — every FR/NFR mapped to its verification
4. [docs/reviews/](docs/reviews/) — three codex red-team rounds and their dispositions (NFR6)
5. [docs/research/](docs/research/) — clink anatomy, token spike, six rounds of LLM A/B benchmarks (v1 pilot → v5 Linux kernel → v6 clangd-LSP shootout), cscope query-engine bug evidence (D17), teaching-layer methodology, benchmark methodology

## Development SOP (rules paid for in blood)

- **Assert every patch**: a string replace that doesn't match must blow up,
  never no-op silently (bitten twice: the ccq CHANGELOG incident, the
  CSCOPE_DB rename incident)
- **Judge tests by exit code**, never by grepping output (Python 3.13's
  colorized unittest defeated the grep for several sessions); locally run
  `NO_COLOR=1 python3 -m unittest discover -s tests -t .`
- **Green at commit time**: ruff + mypy --strict + all three test layers;
  fixtures guard logic, **real repos guard reality** (wpa caught three bugs
  fixtures missed)
- Decisions go into design.md decision records **with their rationale**;
  overturned decisions are not deleted — they get a correction record (the
  D14 pattern)
- Honesty (P7): declare what you can't do, never return empty silently;
  prefer false negatives — fight misses with engine union, fight false
  positives with confidence + tags
- Releasing: CHANGELOG (Keep a Changelog) → version in both places
  (pyproject + VERSION) → tag → counts only when tri-platform CI is green

## Architecture at a glance

```mermaid
flowchart TB
    subgraph fill["Fill layers (each independently re-runnable, touching only its own origin rows)"]
        L0["L0 ctags: nodes + qname disambiguation + signatures"] --> L1["L1 cscope: calls/reads/writes/includes/expands"]
        L1 --> L3["L3 heuristics: callback/fnptr + fnptr.json manual table"]
        L3 --> L4["L4 clink (optional): semantic calls/writes + semantic tags"]
        L4 --> L5["L5 git: hash incremental + co_changes"]
    end
    fill --> DB[("graph.db (schema v2)<br/>meta: db_label + append-only history")]
    DB --> V["query verbs (--json dual output)"] & Z["viz 2D/3D"] & SQL["read-only SQL"]
```

## Tests & lint

```bash
NO_COLOR=1 python3 -m unittest discover -s tests -t .   # judged by exit code
ruff check . && mypy ccodegraph.py
```
integration/e2e skip loudly when cscope/ctags are missing; clink tests use
`CCODEGRAPH_CLINK_PATH` pointing at a locally built binary.
