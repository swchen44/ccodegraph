---
name: ccodegraph
description: Use when navigating or refactoring C/C++ — who calls a function, what it calls, who reads/writes a global, who uses a macro, impact of a change, fn-pointer/callback dispatch, files including a header, co-changing files. Triggers on "誰呼叫", "who calls", "callers of", "who writes", "impact of", "爆炸半徑", "巨集哪裡用", "co-change", or any task needing many grep/Read calls over C/C++. Zero build needed. Every answer carries origin + confidence + tags. C first-class; C++ best-effort.
---

# ccodegraph — C/C++ knowledge graph (SQLite, honesty-labelled)

One graph at `<root>/.ccodegraph/graph.db`; every edge stamped **origin +
confidence + tags**. **If `graph.db` exists the graph is ready — query it
directly. Do NOT run `build`/`schema`/`status` first.** Only two exceptions:
a query errors `no graph` → `build -p <root>` once; you just edited source →
`build --incremental` (cheap, exact) then re-query.

## Command cheatsheet (copy exactly — this file is the complete reference; never run `--help`)

```bash
./ccodegraph.py explore <sym> -p .        # def(file:line,signature)+callers+callees+globals — DEFAULT first move
./ccodegraph.py callers <sym> -p .        # deduped callers, one site + (N sites); includes [fnptr]/[callback] indirect
./ccodegraph.py callees <sym> -p .
./ccodegraph.py impact <sym> -d 2 -p .    # change radius; if it hints about ambiguous edges, rerun with --ambiguous
./ccodegraph.py globals <var> -p .        # writers vs readers, separated
./ccodegraph.py vars-of <fn> -p .         # globals <fn> touches, [reads]/[writes]
./ccodegraph.py who-includes <hdr> -p .   # DIRECT includers, all #include spelling variants, deduped
./ccodegraph.py co-changed <file> -p .    # git co-change statistics (conf 0.50, not semantics)
./ccodegraph.py sql "SELECT … LIMIT 50" -p .   # read-only escape hatch; ALWAYS LIMIT or aggregate
```

`<sym>` = plain name (`eloop_init`) or qname `'src/utils/eloop.c::eloop_init'`
(quote it). Same name defined in several places → per-definition sections; pin
one with the qname. All verbs take `--json`; flags: `--min-conf 0.7` (default),
`--ambiguous`, `--db <path>`, `--limit N`.

Sample (`callers app_init`): `- do_start @ caller.c:3 (2 sites) [cscope; ambiguous 2 candidates; semantic:confirmed]`

**Output caps**: `callers`/`callees`/`explore` print ≤40 rows per section, then
`… +N more (total T; use --limit 0 for all)`; `sql` stops at 200 rows with an
explicit truncation notice. The TRUE TOTAL is always reported — for a full
enumeration rerun with `--limit 0` or a scoped sql query; never treat a
truncated list as complete.

## Token discipline (measured — this is what makes the graph pay for itself)

1. **Graph first, then narrow Read**: the graph cites exact `file:line` — Read
   with offset/limit around it. Never whole-file Read, never `ls` the repo root
   (file list: `sql "SELECT qname FROM nodes WHERE kind='file' AND qname LIKE '%x%' LIMIT 20"`).
2. **Scope queries to the question**: asked about one file/dir? Filter in SQL —
   `sql "SELECT s.qname,e.file,e.line FROM edges e JOIN nodes s ON s.id=e.src
   JOIN nodes d ON d.id=e.dst WHERE d.name='X' AND e.kind='calls' AND e.file
   LIKE 'src/foo%'"` — do NOT run bare `callers` on a high-fan-in symbol
   (hundreds of rows for zero value).
3. `explore` already bundles callers+callees+globals — don't re-query them
   separately.
4. **Before claiming any total, cross-check with one `COUNT(*)` query** — one
   cheap row that catches the classic hand-tally error.
5. Stay in the repo root and use `-p .`; don't `cd` around.

## Schema (embedded — no need to run the `schema` verb)

```
nodes(id, name, qname, kind: function|global|macro|file, file,
      line_start, line_end, signature, is_static, origin, confidence)
edges(src→nodes.id, dst→nodes.id,
      kind: calls|callback|fnptr|reads|writes|includes|expands|co_changes,
      file, line, origin, confidence, meta JSON)      -- one row per SITE
edge_pairs view (src,dst,kind,confidence,first_site,site_count,origins)  -- one row per PAIR
```

## Reading the labels (trust calibration — say what the label says)

conf 1.00 `manual` (user assertion, not proof) · 0.95 `clink`+real compile DB
(single build config only) · 0.93 `clink`+synthesized DB · 0.90 `cscope`
(name-keyed, `#ifdef`-blind: great recall, same-named symbols can mis-bind) ·
0.80 `fnptr` heuristic (field-keyed: `->run()` links every registered `run`) ·
0.70 `callback` (the only signal for qsort-comparator/timer questions — phrase
as "possible caller via callback" unless you read the cited site) · 0.50 `git`.

`[cscope, clink]` on one edge = two independent engines agree (within the
active config). `semantic:confirmed` = clink also saw it (token-level, includes
inactive `#ifdef` regions). `semantic:absent` = clink never successfully parsed
there — a coverage flag, NOT a falsity signal. `ambiguous N candidates` =
same-name definitions; the edge is attached to every viable one — pin by qname;
`impact` skips ambiguous by default (rerun `--ambiguous` when it hints).

## Blind spots — flag these proactively when answer-relevant

- **Struct-field fn-pointer dispatch** (`c->ops->run(c)`): no direct call edge
  exists; `fnptr`/`callback` edges are heuristic. Verify the registration site
  before asserting a dispatch target.
- Macro-GENERATED definitions (`DEFINE_X(foo)` → `foo_handler`): invisible to
  text engines — `sql` LIKE-hunt the generator, then read the macro.
- Object-like macro usage, C++ templates/overloads, computed `#include`: not
  (fully) modelled — fall back to scoped grep.
- Empty result ≠ nothing exists: retry `--min-conf 0.5`, then
  `sql "…name LIKE '%X%'"`, then grep.

## Errors

`no graph` → `build -p <root>` · `symbol not found` → sql LIKE hunt ·
`fnptr … STALE` → rebuild · `clink not found` → optional layer, skip it.

Other verbs (`viz`/`status`/`reset`/`dumpdb`/`skill`/`build`/`clink-import`)
are setup/human-facing — not needed to answer code questions.
