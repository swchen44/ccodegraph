# GT WRQ-016: how many `.c` files directly `#include "server.h"`

**Question (verbatim):** "How many .c files directly #include \"server.h\"?"

**Category:** include-dependency · **Difficulty:** L1

## Method

Two independent counting methods, plus a whole-repo scope check (not just
`src/`), run against the real checkout at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/redis`:

1. `grep -rl --include="*.c" '#include "server.h"' src/ | wc -l`
2. `grep -rc --include="*.c" '#include "server.h"' src/` — per-file occurrence
   counts, to rule out a file being counted once by `-l` while actually
   containing the include twice (would silently inflate a manual line-count
   approach) or the include being duplicated.
3. Repeated both greps rooted at `.` (the whole repo, not just `src/`) to check
   for `.c` files in `deps/`, `tests/`, or `modules/` that also include
   `server.h`, and additionally scanned for alternate include spellings
   (`<server.h>`, path-prefixed forms) via a looser regex.

## Result

**70** `.c` files directly `#include "server.h"`.

- Method 1 (`grep -rl | wc -l`): **70**
- Method 2 (`grep -rc`): every one of those 70 files reports **exactly 1**
  occurrence (`grep -rc ... | awk -F: '$2>1'` → empty) — no file double-includes
  it, so file-count and include-count agree at 70.
- Whole-repo search (`.` instead of `src/`) returns the **identical set of 70
  files**, all still under `src/`. `deps/`, `tests/`, and `modules/` contain
  **zero** `.c` files that include `"server.h"`. The looser include-syntax
  regex (`#include[[:space:]]*[<"]...server\.h[">]`) also returns exactly 70 —
  no file uses `<server.h>` or a path-prefixed include instead.
- All 70 occurrences are live, uncommented `#include "server.h"` directives
  (verified via `grep -rn`, no `//` or `/* */` wrapping on any hit).
- There is exactly one `server.h` in the entire repo (`src/server.h`), so there
  is no ambiguity about which header is meant.
- **Conclusion: no scope ambiguity exists for this question.** Restricting to
  `src/` vs. searching the whole checkout produces the same answer, 70, so the
  "does the question implicitly mean within src/" concern does not create a
  fork in the GT — both readings converge on **70**.
- For context only (not part of the answer): `src/` contains 125 `.c` files
  at its top level, so 70/125 (56%) of them include `server.h`.

### Full file list (70), alphabetical

```
src/acl.c              src/expire.c           src/module.c
src/aof.c              src/fwtree.c           src/multi.c
src/bio.c              src/gcra.c             src/networking.c
src/bitops.c           src/hotkeys.c          src/notify.c
src/blocked.c          src/hyperloglog.c      src/object.c
src/call_reply.c       src/iothread.c         src/pubsub.c
src/childinfo.c        src/keymeta.c          src/rdb.c
src/cluster_asm.c      src/latency.c          src/redis-check-aof.c
src/cluster_legacy.c   src/lazyfree.c         src/redis-check-rdb.c
src/cluster.c          src/logreqres.c        src/replication.c
src/commands.c         src/lolwut.c           src/resp_parser.c
src/config.c           src/lolwut5.c          src/rio.c
src/connection.c       src/lolwut6.c          src/script_lua.c
src/crc16.c            src/lolwut8.c          src/script.c
src/db.c               src/memory_prefetch.c  src/sentinel.c
src/debug.c            src/server.c
src/defrag.c           src/slowlog.c
src/entry.c            src/socket.c
src/estore.c           src/sort.c
src/eval.c             src/sparkline.c
                        src/sparsearray.c
                        src/syncio.c
                        src/t_array.c
                        src/t_hash.c
                        src/t_list.c
                        src/t_set.c
                        src/t_stream.c
                        src/t_string.c
                        src/t_zset.c
                        src/threads_mngr.c
                        src/timeout.c
                        src/tls.c
                        src/tracking.c
                        src/unix.c
```

(70 entries total; layout above is just for readability, not semantically grouped.)

## Scoring rubric (0-3)

- **0** — Count is off by more than 2 from 70 (e.g., wildly wrong from
  grepping only a subdirectory, confusing `#include <server.h>` counts,
  counting `.h` files, or counting `server.h`'s own includes instead of who
  includes it).
- **1** — Count is in the right ballpark (roughly 60-80) but wrong, with no
  file list or method shown to sanity-check — i.e., an unverified guess.
- **2** — Correct count of **70** (or a defensibly-documented alternate count
  if the agent explicitly scoped to something other than plain `grep`, e.g.
  accidentally including/excluding a specific file with justification), but
  without showing/cross-checking via a second method, or without noting that
  `deps/`/`tests/`/`modules/` contribute zero additional files (i.e. doesn't
  address the src/-only vs whole-repo question at all).
- **3** — Exact count **70**, ideally cross-checked by two methods (e.g.
  `grep -rl | wc -l` and `grep -rc` agreeing, or `grep -rl` vs a whole-repo
  search), and explicitly notes that the count is the same whether scoped to
  `src/` or the whole repository (no `.c` file in `deps/`, `tests/`, or
  `modules/` includes `server.h`). Does not need to reproduce the full file
  list to earn full credit, but the number must be exactly 70.

### Common wrong answers and likely causes

- **71+**: likely double-counted a file (e.g. ran `grep -c` and summed
  occurrence counts across files without checking for files with >1 match —
  though in this codebase no file has more than 1, so this specific mistake
  would require a tooling bug, not a real duplicate) or included `server.h`
  itself, or a `.h` file that includes `server.h`, in the tally.
- **69 or fewer**: likely used a non-recursive `grep` (missed a subdirectory
  under `src/`), used `--include=*.c` under a shell where the glob wasn't
  expanded/quoted correctly and silently returned partial results, or
  restricted to a stale/cached file listing (e.g. `cscope.out`) that predates
  a file addition (this repo checkout has several unusual `.c` files such as
  `lolwut5.c`/`lolwut6.c`/`lolwut8.c`/`fwtree.c`/`estore.c`/`gcra.c`/`entry.c`/
  `keymeta.c`/`sparsearray.c`/`t_array.c` that an agent relying on older
  memorized Redis source layouts might not expect and could undercount).
- **A count based on `src/server.h`'s reverse-include closure via clangd/IDE
  "find references"** rather than a plain textual `#include` grep could
  diverge if it (a) also pulls in files that include `server.h` only
  transitively through another header (over-count — the question says
  "directly"), or (b) misses files if the compile database doesn't cover
  every translated `.c` file, e.g. platform-conditional files. The textual
  grep above is the authoritative ground truth for "directly `#include`s".
