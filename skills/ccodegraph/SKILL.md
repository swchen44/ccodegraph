---
name: ccodegraph
description: Use when navigating or refactoring a C/C++ codebase — who calls a function, what it calls, who reads/WRITES a global, who uses a macro, impact of a change, fn-pointer/callback dispatch, files including a header, or files that historically change together. Triggers on "誰呼叫", "who calls", "callers of", "誰改這個全域", "who writes", "impact of", "爆炸半徑", "巨集哪裡用", "#ifdef 這段有人用嗎", "co-change", or any task needing many grep/Read calls over C/C++. Works with ZERO build (no compile_commands.json needed); a compile DB or clink only upgrades precision. Every answer carries origin + confidence + tags — READ THE RISK CHAPTER before trusting any single edge. Scope: C first-class; C++ best-effort (symbols and direct relations recorded, no template/overload resolution).
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
(code changed?) build --incremental      # 1-file change ≈ 4s; no-op ≈ 4s when aligned
```

**Graph freshness**: source-drift detection happens at `build --incremental`
(hash comparison; prints "up to date" when aligned) — `schema` does NOT detect
source drift; its STALE warning is specifically about `fnptr.json` (manual
edges). Unsure whether the graph is current? Run `build --incremental` first —
it is cheap and exact.

## Step 0 — always start with `schema`

```bash
ccodegraph.py schema -p <root> [--json]
```

It tells you: which node/edge kinds are filled and by which origin, how the
graph was built (`engines_run`: full/incremental, compile-DB mode:
`compile-DB(...)` / `merged(...)` / `synthesized(...)`), fnptr.json **STALE
warnings**, and pending layers. Never interpret results without knowing which
engines actually ran.

## Verb reference (all support `--json`)

Symbol input rule (all verbs): pass a plain **name** (`eloop_init`) or a
**qname** (`'src/utils/eloop.c::eloop_init'`) — every verb accepts both; a name
matching several definitions returns per-definition sections; use the qname to
pin one. Quote qnames in the shell (they contain `/` and `::`).

| Verb | Returns | Use when |
|---|---|---|
| `explore X` | definition (signature, file:line) + callers + callees + globals it reads/writes — one shot | **default first move** on any symbol |
| `callers X` | function-level deduped callers, one site + `(N sites)`; **includes `[fnptr]`/`[callback]`-tagged indirect callers and macro users** | who calls / who might dispatch to X |
| `callees X` | what X calls (same edge kinds) | |
| `impact X -d N` | transitive callers by depth. Default N=3; start N=2 on wide-fan-in symbols (log/util functions explode). Skips ambiguous edges by default → if it prints a hint about ambiguous edges, rerun with `--ambiguous` or you WILL underestimate the radius | before a refactor |
| `globals V` | writers vs readers, separated | "who mutates this state" |
| `vars-of F` | globals F touches, `[reads]`/`[writes]` with sites | audit a function's state footprint |
| `who-includes H` | files **directly** including header H (NOT transitive — SQL template 4 for the closure) | header-edit impact |
| `co-changed F` | files historically changing with F (git). **Not subject to `--min-conf`** — statistical layer (conf 0.50), always shown with its count; weigh it yourself | "what else usually moves" |
| `sql 'SELECT …'` | raw rows (connection is read-only) | anything the verbs don't shape |
| `skill` | prints this file | air-gapped install |

Flags: `--min-conf 0.7` (default; applies to call/read/write family, NOT
co-changed), `--ambiguous`, `--json`, `--db <path>`.

### Output shapes (one example each — fields are identical across text/JSON)

```
$ ccodegraph.py callers app_init
callers of app_init — 2 definitions(分節;可用 qname 精確指定):
## alt_init.c::app_init 的定義 @ alt_init.c:1
- do_start  @ caller.c:3  [cscope; ambiguous 2 candidates; semantic:confirmed]
```

```json
$ ccodegraph.py callers app_init --json
{"verb":"callers","symbol":"app_init","min_conf":0.7,"definitions":[
  {"qname":"alt_init.c::app_init","file":"alt_init.c","line":1,"signature":"(void)",
   "items":[{"qname":"do_start","site":"caller.c:3","sites":1,
             "origins":["cscope"],"confidence":0.9,
             "tags":{"ambiguous":true,"candidates":2,"semantic":"confirmed"}}]}]}
```

`tags` in JSON = the parsed `meta` of the edge (same keys); in text they render
inside `[origins; …]`.

## ★ RISK CHAPTER — how to read confidence / origins / tags

Every edge answers three questions: **who said it** (origin), **how reliable is
that engine** (confidence), **what do other engines think** (tags). Nothing
uncertain is deleted — it is labelled. Your job is to read the labels.

### Confidence: what each level means and HOW IT FAILS

| conf | origin | fails by… |
|---|---|---|
| 1.00 | `manual` | being a **user assertion** (asserted_by_user), not a proof; if `schema` shows STALE, the source fnptr.json changed — rebuild before trusting |
| 0.95 | `clink` +real compile DB | seeing only ONE build config; edges in other `#ifdef` configs are invisible to it (not wrong — scoped) |
| 0.93 | `clink` +synthesized DB | same single-config view, plus guessed `-I` (no real `-D`): more code is "inactive" to it |
| 0.90 | `cscope` | being name-keyed and `#ifdef`-blind: sees ALL branches (great recall) but a same-named symbol can mis-bind, and dead-config code counts too |
| 0.80 | `fnptr` heuristic | field-keyed dispatch approximation: `->run()` links to every registered `run` handler (fanout-capped) |
| 0.70 | `callback` | **passes the default threshold on purpose** — it is the only signal for qsort-comparator/signal-handler questions. Phrase these as "possible caller via callback" unless you have read the cited site; a same-named local passed as an argument can fake one |
| 0.50 | `git` (co_changes) | being statistics, not semantics |

### Origins: agreement is evidence — scoped evidence

`[cscope, clink]` on one pair = independent text + semantic engines agree —
strong **within the active build config** (it says nothing about other
configs). A single `[callback]` = heuristic only. Union philosophy: missing
edges are fought with multiple engines, false edges with labels; filtering is
YOUR call (`--min-conf`), never silent deletion.

### `semantic: confirmed | absent` — the #ifdef signal

- `confirmed` — libclang also sees this edge in the active config.
- `absent` — **not confirmed by the active semantic config**. Most common
  causes: inactive `#ifdef` branch, other-platform file (measured on wpa:
  13,895 absent, essentially all config-gated). Rarely it can also be a
  name-keyed mis-bind from cscope — when the answer matters, open the cited
  `file:line` to distinguish. Confidence is deliberately NOT lowered for
  absent: absence here is a clue, not a verdict.
- **"這段 `#ifdef` 有人用嗎" recipe**: `callers <fn-inside-the-block>` — edges
  tagged `semantic:absent` but present via cscope = referenced by code that is
  compiled out in this config; nothing at all = likely dead in every config
  the text layer can see.

### `ambiguous N candidates` — same-name multiple definitions

The graph attaches such edges to every viable candidate and labels them
(static functions already bound same-file / header-static to includers; what
remains is genuinely undecidable at text level).
- `callers`/`explore` SHOW them (labelled).
- `impact` SKIPS them by default; on the empty-result hint, rerun
  `--ambiguous` and judge candidates yourself.
- Pin one definition by qname: `callers 'eloop.c::eloop_init'`.

## Errors & what to do next

| Message | Next step |
|---|---|
| `ERROR: no graph at …` | `build -p <root>` first |
| `symbol "X" not found` | name is exact-match: hunt with `sql "SELECT qname,kind FROM nodes WHERE name LIKE '%X%'"` |
| `(no unambiguous impact; N ambiguous edges…)` | rerun with `--ambiguous` |
| `WARNING: fnptr.json changed … STALE` | `build` (full or `--incremental`) to re-ingest manual edges |
| `ERROR: clink not found` | semantic layer is optional — skip it, or install clink / set `CCODEGRAPH_CLINK` |
| `ERROR: clink db schema user_version=…` | clink upgraded its schema; update the importer (do not ignore) |
| `ERROR: … Universal Ctags` | install universal-ctags (message includes per-OS commands) |

## Blind spots (measured, not guessed)

| Blind spot | Reality | Fallback |
|---|---|---|
| macro-GENERATED definitions (`DEFINE_HANDLER(foo)` → `foo_handler`) | invisible to every text layer; clink+real-DB may see it | `sql` LIKE-search the generator, read the macro |
| object-like macro usage (`#define N 5` … `x = N;`) | `expands` edges are verified for function-like macros; object-like usage may not appear | `sql`: search nodes kind='macro', then grep the name |
| C++ templates/overloads | best-effort symbols only (W3) | clangd-based tooling for C++-heavy work |
| name-keyed shadowing | a local named like a global/function can miscount | check the cited `file:line` |
| computed/non-literal `#include` | not modelled | grep |

## SQL escape hatch (read-only; schema contract v1)

```sql
-- nodes(id INTEGER PK, name, qname, kind: function|global|macro|file, file,
--       line_start, line_end, signature, is_static, origin, confidence)
-- edges(src→nodes.id, dst→nodes.id,
--       kind: calls|callback|fnptr|reads|writes|includes|expands|co_changes,
--       file, line, origin, confidence, meta JSON)   -- meta = the "tags"
-- 一列一站點;pair 級用 edge_pairs 視圖(src,dst,kind,confidence,first_site,
--       site_count,origins)

-- 1. dead-ish functions: defined, never called/dispatched
SELECT n.qname FROM nodes n WHERE n.kind='function' AND NOT EXISTS
  (SELECT 1 FROM edges e WHERE e.dst=n.id AND e.kind IN ('calls','callback','fnptr'));

-- 2. every call site of Y inside one caller X (all sites, not just the first)
SELECT e.file, e.line FROM edges e JOIN nodes s ON s.id=e.src
  JOIN nodes d ON d.id=e.dst WHERE s.name='X' AND d.name='Y'
  AND e.kind='calls' ORDER BY e.file, e.line;

-- 3. hottest globals by writer count
SELECT d.qname, COUNT(DISTINCT e.src) w FROM edges e JOIN nodes d ON d.id=e.dst
  WHERE e.kind='writes' GROUP BY d.qname ORDER BY w DESC LIMIT 10;

-- 4. TRANSITIVE include closure of header H (who rebuilds if H changes)
WITH RECURSIVE inc(id) AS (
  SELECT id FROM nodes WHERE kind='file' AND qname='H'
  UNION
  SELECT e.src FROM edges e JOIN inc ON e.dst=inc.id WHERE e.kind='includes')
SELECT DISTINCT n.qname FROM inc JOIN nodes n ON n.id=inc.id;
```

## Agent guidance

- **Graph first, grep last.** Ask the graph, then Read the exact `file:line` it
  cites. Reversing the order is what burns tokens (measured 13–90×).
- Empty result ≠ nothing exists: check `schema` (layer pending? STALE?), the
  blind-spot table, then `--ambiguous` / `--min-conf 0.5`.
- After editing code: `build --incremental` — the graph is only trustworthy
  when aligned with the tree.
- Prefer `--json` when you will chain the data; text when a human reads it.
