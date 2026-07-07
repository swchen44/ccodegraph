# GT WRQ-002: definition of createStringObject()

Question ID: WRQ-002 (category: symbol-definition, difficulty: L1)

Question (verbatim):
"Find the definition of createStringObject(). Return file, line, and full signature."

Method: 直接對 repo 原始碼 grep + Read 逐行核對(非猜測),並交叉檢查標頭檔宣告、
同名/相似名稱函式、以及 build 層(Makefile)是否有 `#ifdef`/條件編譯把 object.c
排除在編譯之外。

## 定義(Definition)— 明確答案

- **File**: `src/object.c`
- **Line**: 338
- **Full signature**: `robj *createStringObject(const char *ptr, size_t len)`

證據(逐行讀取 src/object.c:331-343):

```
331: /* Create a string object with EMBSTR encoding if it is smaller than
332:  * OBJ_ENCODING_EMBSTR_SIZE_LIMIT, otherwise the RAW encoding is
333:  * used.
334:  *
335:  * The current limit of 44 is chosen so that the biggest string object
336:  * we allocate as EMBSTR will still fit into the 64 byte arena of jemalloc. */
337: #define OBJ_ENCODING_EMBSTR_SIZE_LIMIT 44
338: robj *createStringObject(const char *ptr, size_t len) {
339:     if (len <= OBJ_ENCODING_EMBSTR_SIZE_LIMIT)
340:         return createEmbeddedStringObject(ptr,len);
341:     else
342:         return createRawStringObject(ptr,len);
343: }
```

Body confirms this is the true definition (has a function body, dispatches to
`createEmbeddedStringObject`/`createRawStringObject` based on length vs the 44-byte
EMBSTR limit) — not a stub or macro wrapper.

## 宣告 vs 定義(declaration-vs-definition trap)— 已核實

- `grep -rn "createStringObject(" --include="*.h" .` across the whole repo returns
  exactly **one** header hit: `src/object.h:139`:
  ```
  139: robj *createStringObject(const char *ptr, size_t len);
  ```
  This is the forward declaration (prototype, no body, ends in `;`).
- **Correction to the draft evaluation_notes**: the draft says "not any forward
  declaration in server.h". That phrasing is misleading — `createStringObject` has
  **no declaration written directly in `server.h`** at all; the actual prototype
  lives in **`src/object.h:139`**. `server.h` merely transitively pulls it in via
  `#include "object.h"` at `src/server.h:24`. So the more precise, verified statement
  is: *"the declaration is in `src/object.h:139`; `server.h` only re-exposes it via
  `#include "object.h"`; the definition (function body) is in `src/object.c:338`."*
  A grading agent that answers "declared in server.h, defined in object.c" is
  directionally fine (server.h does transitively expose the prototype) but an agent
  that says "declared in object.c" or points at the header line as if it were the
  definition should be marked wrong — see rubric.

## 相似命名檢查(similar-name confusion check)— 已核實

A shallow/fuzzy grep for "createStringObject" can pull in unrelated sibling
functions in the same file. Confirmed distinct symbols, all in `src/object.c`,
none of which is the one asked about:

- `createStringObjectFromLongLongWithOptions` — line 364
- `createStringObjectFromLongLong` — line 385 (wrapper around the above)
- `createStringObjectFromLongLongForValue` — line 394
- `createStringObjectFromLongLongWithSds` — line 405
- `createStringObjectFromLongDouble` — line 415
- `tryCreateStringObject` — line 353 (same-arity/near-identical-purpose sibling: same
  signature `robj *tryCreateStringObject(const char *ptr, size_t len)`, but returns
  NULL on allocation failure instead of never failing — **not** the exact symbol
  asked about, must not be substituted)
- `createRawStringObject` / `tryCreateRawStringObject` / `createEmbeddedStringObject`
  — helpers called *by* `createStringObject`, not the symbol itself.

**CORRECTION (2026-07-08, found during codex independent scoring of the v3 run)**:
the original pass of this GT wrongly classified `deps/hiredis/hiredis.c` as merely a
call site. It is not — `deps/hiredis/hiredis.c:125` is a **second, genuine, unrelated
definition** of a function also named `createStringObject`:

```
60:  static void *createStringObject(const redisReadTask *task, char *str, size_t len);
...
125: static void *createStringObject(const redisReadTask *task, char *str, size_t len) {
```

This is a `static` (file-local) helper inside the vendored hiredis RESP-protocol
parser (`deps/hiredis/`, a separate C client library bundled with redis-server, not
part of it) — different return type (`void *` vs `robj *`), different parameter list
(`const redisReadTask *task, char *str, size_t len` vs `const char *ptr, size_t len`),
different purpose (building a reply object during RESP parsing vs allocating a
redis-server string value), and `static` linkage means it cannot collide at link time
with `src/object.c`'s `createStringObject` — but it is a textually real, same-name
symbol that a whole-repo (non-`static`-aware) grep will legitimately surface.
**Four independent agents in the v3 benchmark run all correctly surfaced this real
second definition** (initially treated as a scoring flaw by the codex-graded pass
that trusted this GT's original, incomplete claim — re-scored to full credit; noting
the disambiguating symbol is precise, correct behavior, not a hallucination). Besides
this one genuine collision, all other `.c` hits for `createStringObject` (`src/t_string.c`,
`src/db.c`, `src/rdb.c`, `src/module.c`, `src/cluster_legacy.c`, `src/notify.c`, etc.)
are confirmed call sites of `src/object.c:338`, not redefinitions.

## Build-system-level check (Makefile)

Checked `src/Makefile` for any `#ifdef`/conditional exclusion of `object.c` from the
build (the earlier-round failure mode this benchmark specifically guards against).
`object.c` is unconditionally listed in `REDIS_SERVER_OBJ` (src/Makefile:387,
`... networking.o util.o object.o db.o ...`) with no surrounding `ifdef`/`ifndef`
guard — it is always compiled into `redis-server`, no build flag gates it out.
No Makefile-level trap applies to this question.

Scope note: the question has no explicit scope limiter (e.g. no "only under src/",
no "excluding tests/deps") — so this is a whole-repo lookup, and the whole-repo grep
above was run to be safe. **Corrected 2026-07-08**: a real naming collision WAS found
outside `src/object.c` — see the correction note above (`deps/hiredis/hiredis.c:125`,
a distinct `static` function, different signature/purpose). Noting it correctly is a
precision bonus and must NOT be treated as a flaw or hallucination when grading.

## Scoring rubric (0-3)

- **Score 3**: File `src/object.c`, line `338` (±1 line acceptable for whitespace/comment
  offset drift), full signature `robj *createStringObject(const char *ptr, size_t len)`
  (return type `robj *` and both parameters present, names may vary e.g. `s`/`length`
  as long as types match). Answer must point at the function **body**, not the
  `object.h:139` prototype, as "the definition."
- **Score 2**: Correct file (`src/object.c`) and correct function identified, but line
  number is off by more than a couple of lines (e.g. cites a line inside the function
  body, or cites the doc-comment/macro line 331-337 instead of 338), or signature is
  slightly incomplete (e.g. missing `const` or drops a parameter type) but otherwise
  clearly the right symbol.
- **Score 1**: Points at `src/object.h:139` and calls that "the definition" (declaration
  mistaken for definition — the classic header/impl trap), OR answers with a
  same-family-but-wrong symbol (e.g. `createStringObjectFromLongLong`,
  `tryCreateStringObject`, `createRawStringObject`) instead of the exact
  `createStringObject` asked about.
- **Score 0**: Wrong file entirely, fabricated line number, or no verifiable
  file:line evidence given.
