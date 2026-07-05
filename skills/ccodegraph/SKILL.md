---
name: ccodegraph
description: Use when navigating or refactoring a C/C++ codebase — who calls a function, what it calls, who reads/WRITES a global, who uses a macro, impact of a change, fn-pointer dispatch, files including a header, or files that historically change together. Triggers on "誰呼叫", "who calls", "callers of", "誰改這個全域", "who writes", "impact of", "爆炸半徑", "巨集哪裡用", "#ifdef 這段有人用嗎", "co-change", or any task needing many grep/Read calls over C/C++. Works with ZERO build (no compile_commands.json needed); a compile DB or clink only upgrades precision. Every answer carries origin + confidence + tags — READ THE RISK CHAPTER before trusting any single edge. Scope: C first-class; C++ best-effort (symbols and direct relations recorded, no template/overload resolution).
---

# ccodegraph — C/C++ knowledge graph for agents (multi-engine, honesty-labelled)

One SQLite graph (`<root>/.ccodegraph/graph.db`) filled by layered engines
(ctags → cscope → heuristics → optional clink/libclang → git), every row stamped
with **origin + confidence + tags**. You do the high-level judgement; the graph
does the mechanical work (attribution, dedup, aggregation). Measured: 13–90×
fewer bytes ingested than grep/Read loops per question.

## The journey

```
ccodegraph.py build -p <root>            # zero-build; ~90s for a 600-file repo
ccodegraph.py clink-import -p <root>     # OPTIONAL semantic layer (needs clink binary)
… query verbs (repeat freely, ~100ms each) …
(code changed?) build --incremental      # 1-file change ≈ 4s, provably equal to full
```

## Step 0 — always start with `schema`

```bash
ccodegraph.py schema -p <root> [--json]
```

It tells you: which node/edge kinds are filled and by which origin, how the
graph was built (`engines_run`: full/incremental, compile-DB mode), **STALE
warnings** (fnptr.json changed since build → manual edges outdated → re-run
build), and which layers are pending. Never interpret query results without
knowing which engines actually ran.

## Verb reference (all support `--json`; pick the format YOU parse best)

| Verb | Returns | Use when |
|---|---|---|
| `explore X` | definition (signature, file:line) + callers + callees + globals it reads/writes — one shot | **default first move** on any symbol |
| `callers X` / `callees X` | function-level, deduped, one site + `(N sites)` count, per-definition sections | who calls / what does it call (macros too: `callers MAX2`) |
| `impact X -d N` | transitive callers by depth; excludes ambiguous edges by default | before a refactor; see risk chapter for `--ambiguous` |
| `globals V` | writers vs readers, separated | "who mutates this state" — grep answers this badly |
| `vars-of F` | globals F touches, `[reads]`/`[writes]` labelled with sites | audit a function's state footprint |
| `who-includes H` | files including header H | header-edit rebuild impact |
| `co-changed F` | files that historically change with F (git, count) | "if I touch this, what else usually moves" |
| `sql 'SELECT …'` | raw rows (connection is read-only) | anything the verbs don't shape |

Flags: `--min-conf 0.7` (default threshold), `--ambiguous` (impact walks
multi-candidate edges), `--json`, `--db <path>`.

## ★ RISK CHAPTER — how to read confidence / origins / tags

Every edge answers three questions: **who said it** (origin), **how reliable is
that engine** (confidence), **what do other engines think** (tags). Nothing
uncertain is deleted — it is labelled. Your job is to read the labels.

### Confidence: what each level means and HOW IT FAILS

| conf | origin | fails by… |
|---|---|---|
| 1.00 | `manual` | being a **user assertion** (asserted_by_user), not a proof; if `schema` shows STALE, the source fnptr.json changed — rebuild before trusting |
| 0.95 | `clink` +real compile DB | seeing only ONE build config; edges in other `#ifdef` configs are invisible to it (not wrong — scoped) |
| 0.93 | `clink` +synthesized DB | same single-config view, plus guessed `-I` (no real `-D`): inactive-#ifdef code is invisible |
| 0.90 | `cscope` | being name-keyed and `#ifdef`-blind: sees ALL branches (great recall) but a same-named local can shadow, and dead-config code counts too |
| 0.80 | `fnptr` heuristic | field-keyed dispatch approximation: `->run()` links to every registered `run` handler (fanout-capped) |
| 0.70 | `callback` heuristic | a same-named local variable passed as an argument can fake an edge — verify surprising ones at their `file:line` |
| 0.50 | `git` (co_changes) | being statistics, not semantics: correlation from commit history |

### Origins: agreement is evidence

- `[cscope, clink]` on one pair = independent text + semantic engines agree — strong.
- `[callback]` alone = heuristic only — trust but verify at the site if the answer matters.
- Union philosophy: missing edges are fought with multiple engines, false edges
  with labels. Filtering happens at YOUR end (`--min-conf`), never by deletion.

### `semantic: confirmed | absent` — the #ifdef signal

After `clink-import`, every cscope calls/writes edge is annotated:
- `confirmed` — the semantic engine (libclang) also sees it in the active config.
- `absent` — **NOT a false edge.** It usually means the call lives in an
  inactive `#ifdef` branch or another platform's file. Measured on wpa: 13,895
  absent edges, essentially all config-gated code. Treat as: "real code, not in
  this build config". Confidence is deliberately NOT lowered for absent.

### `ambiguous N candidates` — same-name multiple definitions

C repos define the same function name in several files (eloop.c vs
eloop_win.c). The graph attaches the edge to every viable candidate and labels
it. Rules already applied for you: static functions bind same-file (C
semantics; header statics bind to includers); what remains is genuinely
undecidable at text level.
- `callers` SHOWS ambiguous edges (with the label) — you see both candidates.
- `impact` SKIPS them by default (pollution control). If impact returns empty
  with a hint about ambiguous edges, rerun with `--ambiguous` and judge
  candidates yourself.
- To pin one definition: query by qname (`callers 'eloop.c::eloop_init'`).

### Graph-level provenance

`schema --json` → `engines_run` tells you: full vs incremental build, compile-DB
mode (`merged(3 DBs…)` / `compile-DB(...)` / `synthesized(...)`). A synthesized
mode means the semantic layer had guessed includes and no `-D` — weigh
`semantic:absent` accordingly (more of it, still meaningful).

## Blind spots (measured, not guessed)

| Blind spot | Reality | Fallback |
|---|---|---|
| macro-GENERATED definitions (`DEFINE_HANDLER(foo)` → `foo_handler`) | invisible to every text layer; clink+real-DB may see it | `sql` LIKE-search the generator, read the macro |
| C++ templates/overloads | recorded as best-effort symbols only (W3) | use clangd-based tooling for C++-heavy work |
| name-keyed shadowing | a local named like a global/function can miscount | check the `file:line` the edge cites |
| includes via computed paths / non-literal `#include` | not modelled | grep |

## SQL escape hatch (read-only; schema contract v1)

```sql
-- nodes(name, qname, kind: function|global|macro|file, file, line_start, line_end,
--       signature, is_static, origin, confidence)
-- edges(src, dst, kind: calls|callback|fnptr|reads|writes|includes|expands|co_changes,
--       file, line, origin, confidence, meta JSON)
-- 站點全存:一列一個呼叫點;pair 級用 edge_pairs 視圖

-- 1. dead-ish functions: defined, never called, never taken as callback/fnptr
SELECT n.qname FROM nodes n WHERE n.kind='function' AND NOT EXISTS
  (SELECT 1 FROM edges e WHERE e.dst=n.id AND e.kind IN ('calls','callback','fnptr'));

-- 2. every call site of X inside one caller (all sites, not just the first)
SELECT e.file, e.line FROM edges e JOIN nodes s ON s.id=e.src
  JOIN nodes d ON d.id=e.dst WHERE s.name='wpa_driver_nl80211_scan'
  AND d.name='wpa_printf' AND e.kind='calls' ORDER BY e.file, e.line;

-- 3. hottest globals by writer count
SELECT d.qname, COUNT(DISTINCT e.src) w FROM edges e JOIN nodes d ON d.id=e.dst
  WHERE e.kind='writes' GROUP BY d.qname ORDER BY w DESC LIMIT 10;
```

## Agent guidance

- **Graph first, grep last.** Ask the graph, then Read the exact `file:line` it
  cites. Reversing the order is what burns tokens (measured 13–90×).
- Empty result ≠ nothing exists: check `schema` (layer pending? STALE?), then
  the blind-spot table, then consider `--ambiguous` / `--min-conf 0.5`.
- After editing code: `build --incremental` (seconds) — the graph is only
  trustworthy when aligned with the tree; `schema` shows the last build mode.
- Prefer `--json` when you will chain the data; prefer text when a human reads it.
