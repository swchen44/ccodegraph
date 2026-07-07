# GT WRQ-007: every function in t_string.c reaching setKeyByLink() (direct or via setGenericCommand())

**Category**: caller-callee | **Difficulty**: L3

## Question (verbatim)

> Find every function in src/t_string.c that calls setKeyByLink() (defined in src/db.c),
> directly or by first calling setGenericCommand().

Scope limiter to respect: the question defines exactly two accepted paths to count as
"calls setKeyByLink()" — (a) a **direct** call to `setKeyByLink(...)` from within the
function's own body, or (b) the function calls `setGenericCommand(...)`, which in turn
calls `setKeyByLink(...)`. Any other transitive path to `setKeyByLink()` that does NOT
go through `setGenericCommand()` is explicitly out of scope, even if it reaches the same
target function. This matters concretely in this file: `setKey()` (src/db.c:742) is a
thin wrapper that also calls `setKeyByLink(c, db, key, valref, flags, NULL)` internally,
and `msetGenericCommand()` (src/t_string.c:756, called by `msetCommand`/`msetnxCommand`)
and `msetexCommand()` (src/t_string.c:821) both call `setKey()` directly — but neither
calls `setGenericCommand()` nor `setKeyByLink()` directly, so per the question's own
literal wording (direct, or via `setGenericCommand()` specifically) they must be
**excluded**. An answer that includes the mset family by loosely reasoning "it reaches
setKeyByLink eventually" is over-answering relative to what was actually asked.

## Method

1. Read prior work first: `docs/research/hard-benchmark/gt_case2_set_chain.md`, which
   traces `setCommand -> setGenericCommand -> setKeyByLink` for the SET command
   specifically and cites `setKeyByLink` defined at `src/db.c:754`, called from
   `t_string.c:95` in that (older) checkout snapshot.
2. Re-verified in the current checkout (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/redis`):
   - `grep -n "setKeyByLink(" src/db.c` → definition now at **src/db.c:754** (line number
     matches the prior doc) and one internal call at `src/db.c:743` inside `setKey()`
     (not inside `t_string.c`, so not itself an answer — see scope note above).
   - `grep -n "setKeyByLink(" src/t_string.c` → exactly **one** hit, `t_string.c:181`,
     inside the body of `setGenericCommand()` (defined `t_string.c:87`). The call site
     has shifted from the old doc's `t_string.c:95` to `t_string.c:181` in this checkout —
     confirmed by reading `t_string.c:87-135` and observing the call sits directly inside
     `setGenericCommand()`'s body, immediately after the `setkey_flags` computation.
3. `grep -n "setGenericCommand(" src/t_string.c` → hits at lines 40 (comment prose, not a
   call), 87 (the definition), and four real call sites: **443, 448, 453, 458**. Read
   `t_string.c:430-470` to identify the enclosing function for each:
   - line 443 → inside `setCommand()` (def at `t_string.c:435`)
   - line 448 → inside `setnxCommand()` (def at `t_string.c:446`)
   - line 453 → inside `setexCommand()` (def at `t_string.c:451`)
   - line 458 → inside `psetexCommand()` (def at `t_string.c:456`)
   No other call sites of `setGenericCommand(` exist in the file (the remaining two hits,
   756/814/818, are `msetGenericCommand` — a different, unrelated function name that only
   shares a substring — its own definition and its two callers `msetCommand`/`msetnxCommand`).
4. Checked every other candidate the task description flagged as plausible, to avoid
   both false negatives and false positives:
   - `getexCommand()` (`t_string.c:499-556`): full body read — calls `setExpire()` only
     (line 536), never `setKeyByLink` or `setGenericCommand`. **Not included.**
   - `increxCommand()` (`t_string.c:1196-1368`): full body read — calls `setExpire()` only
     (line ~1344), never `setKeyByLink` or `setGenericCommand`. **Not included.**
   - `msetexCommand()` (`t_string.c:821-900`): calls `setKey()` (src/db.c:742), not
     `setGenericCommand()` and not `setKeyByLink()` directly. Per the question's literal
     two-path definition, **not included** (see scope note above).
   - `msetGenericCommand()` / `msetCommand()` / `msetnxCommand()`: same reasoning as
     `msetexCommand()` — reach `setKeyByLink` only via `setKey()`, never via
     `setGenericCommand()`. **Not included.**
5. Cross-check with a second, independent method: searched for any function-pointer /
   macro-indirection style reference (`&setGenericCommand`, `&setKeyByLink`, or a
   `#define` aliasing either name) anywhere in `src/` — zero hits. `setGenericCommand`
   and `setKeyByLink` are called only in plain, direct C call syntax; no dispatch table,
   no macro wrapper, no case where a caller could be hidden from a plain-text grep.
6. Build-system-level check (the specific failure mode this benchmark round guards
   against): `grep -n "#ifdef\|#ifndef" src/t_string.c` → **zero matches** — the file
   has no conditional-compilation blocks at all, so none of the functions in scope could
   be excluded from a given build by an `#ifdef`. At the Makefile level,
   `src/Makefile`'s `REDIS_SERVER_OBJ` list includes both `t_string.o` and `db.o`
   unconditionally (no surrounding `ifdef` in the object list) — both translation units
   are always compiled into every standard redis-server build. No build-system exclusion
   applies to any function in the result set below.

## Result: exactly 5 functions in src/t_string.c reach setKeyByLink()

| # | Function | Definition (file:line) | Call depth | Evidence (file:line) |
|---|----------|------------------------|------------|------------------------|
| 1 | `setGenericCommand()` | `src/t_string.c:87` | **1** (direct) | calls `setKeyByLink(...)` at `src/t_string.c:181` |
| 2 | `setCommand()` | `src/t_string.c:435` | **2** (via `setGenericCommand`) | calls `setGenericCommand(...)` at `src/t_string.c:443` |
| 3 | `setnxCommand()` | `src/t_string.c:446` | **2** (via `setGenericCommand`) | calls `setGenericCommand(...)` at `src/t_string.c:448` |
| 4 | `setexCommand()` | `src/t_string.c:451` | **2** (via `setGenericCommand`) | calls `setGenericCommand(...)` at `src/t_string.c:453` |
| 5 | `psetexCommand()` | `src/t_string.c:456` | **2** (via `setGenericCommand`) | calls `setGenericCommand(...)` at `src/t_string.c:458` |

`setKeyByLink()` itself is defined in `src/db.c:754` (matches the citation in
`gt_case2_set_chain.md`; the call site inside `setGenericCommand()` has moved from
`t_string.c:95` in the prior doc's checkout to `t_string.c:181` in this checkout —
noted so a grader isn't thrown by the line-number drift between docs).

**Explicitly NOT in the result set** (reach `setKeyByLink` only via `setKey()`, which is
outside the question's "direct or via setGenericCommand" scope):
`msetGenericCommand()` (t_string.c:756), `msetCommand()` (t_string.c:813),
`msetnxCommand()` (t_string.c:817), `msetexCommand()` (t_string.c:821).

**Confirmed NOT related to setKeyByLink at all** (candidates suggested as plausible but
verified to not reach it by any path): `getexCommand()` (t_string.c:499),
`increxCommand()` (t_string.c:1196) — both only touch `setExpire()`, a sibling TTL-only
function, never the key-write path.

## Scoring rubric (0-3)

- **3**: Lists all 5 functions (`setGenericCommand`, `setCommand`, `setnxCommand`,
  `setexCommand`, `psetexCommand`) with correct call depth for each (1 for
  `setGenericCommand`, 2 for the other four), and does not add the mset family,
  `getexCommand`, or `increxCommand` as false positives. File:line evidence may be
  approximate (±2 lines) but must point at the right function bodies.
- **2**: Gets all 5 functions right but mislabels call depth for one or more (e.g. calls
  `setGenericCommand` depth 2, or calls one of the four wrapper commands depth 1), OR
  is missing exactly one of the 5 functions, OR includes one plausible-but-wrong extra
  (e.g. `msetexCommand`) while otherwise correct.
- **1**: Only finds `setCommand` (the case already covered by prior research doc
  gt_case2_set_chain.md) and misses `setnxCommand`/`setexCommand`/`psetexCommand`
  entirely, i.e. shallow reuse of the SET-only chain without generalizing to the other
  three thin wrappers that share `setGenericCommand`. Also this tier if 2+ functions are
  missing or 2+ depth misclassifications occur.
- **0**: Misses `setGenericCommand` itself (the depth-1 case) entirely, or fabricates
  functions/line numbers not verifiable in the file, or claims the mset family / getex /
  increx belong in the set (fundamental scope confusion about what "via
  setGenericCommand" means).
