# GT WRQ-022: WRONGTYPE reply construction site in the SET command path

**Question (verbatim):** "A user sees a WRONGTYPE error when running SET on an
existing key. Find where this specific error reply is constructed in the SET
command path (not other commands)."

**Category:** bug-localization · **Difficulty:** L2

**evaluation_notes (from questions.jsonl):** "Should land on the type-check
inside setGenericCommand or a shared helper it calls, not a different
command's WRONGTYPE check."

Repo investigated: `/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/redis`
(real checkout, HEAD `08b465e4f4891bef9f08d7049dd670627b86f7a4`, 2026-06-26).
Prior established chain: `gt_case2_set_chain.md` (read first — traces
`setCommand` → `setGenericCommand` → `setKeyByLink` → `dbSetValue`/
`dbAddByLink` for the normal write path; that file does **not** cover the
WRONGTYPE branches, which is what this question is testing).

## Key fact that resolves the scope-limiter ("not other commands")

`src/commands/set.json` line 3 documents SET's summary as: **"Sets the string
value of a key, ignoring its type."** This is confirmed by the code: plain
`SET key value` on an existing key of any type (list, hash, etc.) does **not**
type-check at all — it unconditionally overwrites via `setKeyByLink` →
`dbSetValue`/`dbAddByLink` (see `gt_case2_set_chain.md`). There is **no**
WRONGTYPE check on that plain path.

SET can only produce WRONGTYPE on an *existing* key when the command uses one
of two option families that are exclusively parsable for `COMMAND_SET`
(confirmed in `parseExtendedStringArgumentsOrReply`, `src/t_string.c:301-428`):

- the `GET` option (`SET key value GET`) — flag bit only ever set at
  `src/t_string.c:338`, gated by `(command_type == COMMAND_SET)` — i.e. this
  flag can *only* be set by `setCommand`, never by `setnxCommand`/
  `setexCommand`/`psetexCommand`/`getsetCommand` even though they share the
  same `setGenericCommand()` body.
- the compare-and-set options `IFEQ`/`IFNE`/`IFDEQ`/`IFDNE` — same gating,
  only settable for `COMMAND_SET` (`src/t_string.c:396-420`).

Both are genuinely "the SET command path" (reached only from `setCommand`),
and both terminate in the exact same shared helper: `checkType()`
(`src/object.c:884`).

## Call chains (file:line, read end-to-end, not grepped)

### Chain A — via the `GET` option (canonical/most-documented case)

1. `setCommand` (`src/t_string.c:435`) parses args via
   `parseExtendedStringArgumentsOrReply(c, 3, &args, COMMAND_SET)`; if the
   client sent `... GET`, `args.flags` gets `OBJ_SET_GET` set
   (`src/t_string.c:338`).
2. `setCommand:443` calls `setGenericCommand(c, args.flags, ...)`.
3. Inside `setGenericCommand` (`src/t_string.c:87`), **line 99-101**:
   ```c
   if (flags & OBJ_SET_GET) {
       if (getGenericCommand(c) == C_ERR) return;
   }
   ```
   This runs *before* the existence lookup / overwrite logic, i.e. it is
   SET's own "return-old-value" step, reusing `getGenericCommand` as a
   subroutine call — not a dispatch to the GET command.
4. `getGenericCommand` (`src/t_string.c:461`), **line 467**:
   ```c
   if (checkType(c,o,OBJ_STRING)) {
       return C_ERR;
   }
   ```
5. `checkType()` (`src/object.c:884-891`) — **the actual construction site**:
   ```c
   int checkType(client *c, robj *o, int type) {
       if (o && o->type != type) {
           addReplyErrorObject(c,shared.wrongtypeerr);   // src/object.c:887
           return 1;
       }
       return 0;
   }
   ```
   `addReplyErrorObject(c,shared.wrongtypeerr)` at **`src/object.c:887`** is
   where the WRONGTYPE reply object is actually written to the client output
   buffer. `shared.wrongtypeerr` itself is a pre-built shared reply object
   (declared `src/server.h:1732`, initialized in `createSharedObjects()` in
   `src/server.c` to `"-WRONGTYPE Operation against a key holding the wrong
   kind of value\r\n"`).
6. Back in `getGenericCommand`, `C_ERR` propagates up; `setGenericCommand`
   line 100 sees `C_ERR` and does a bare `return;` — the command ends here,
   the key is never overwritten.

### Chain B — via `IFEQ`/`IFNE`/`IFDEQ`/`IFDNE` (compare-and-set options)

1. `setCommand` → `setGenericCommand` as above, with e.g. `OBJ_SET_IFEQ` set.
2. `setGenericCommand`, **line 117-121**:
   ```c
   if (found && (flags & (OBJ_SET_IFEQ | OBJ_SET_IFNE | OBJ_SET_IFDEQ | OBJ_SET_IFDNE))) {
       kvobj *current = lookupKeyRead(c->db, key);
       if (checkType(c, current, OBJ_STRING)) {   // t_string.c:119
           return;
       }
   ```
   Here `checkType()` is called *directly* inline in `setGenericCommand`
   (not via `getGenericCommand`), against the pre-existing value, before the
   digest/value comparison logic runs.
3. Same terminal construction site: `checkType()` →
   `addReplyErrorObject(c,shared.wrongtypeerr)` at **`src/object.c:887`**.

## Why both chains are legitimately "the SET path" and not another command

- `checkType()` (`src/object.c:884`) is genuinely shared infrastructure —
  it is also called from `getGenericCommand` when reached via plain `GET`
  (`getCommand` → `getGenericCommand`, `t_string.c:475`/`461`), from
  `getexCommand` (`t_string.c:511`), from list/hash/set commands, etc. The
  *construction code* is identical everywhere; that is expected and is not
  a mistake.
- What makes an answer SET-specific is the **call site**, not the
  `checkType` body: `t_string.c:119` is called only from inside
  `setGenericCommand`, and `t_string.c:100`'s call into `getGenericCommand`
  is only reachable when `OBJ_SET_GET` is set, which (per
  `parseExtendedStringArgumentsOrReply`'s `command_type == COMMAND_SET`
  gating) can only happen when the top-level command is `SET` — `SETNX`,
  `SETEX`, `PSETEX`, and `GETSET` all call the same `setGenericCommand`/
  `getGenericCommand` functions but can never set `OBJ_SET_GET` or the
  `IFEQ` family themselves (they pass fixed flags, see `t_string.c:446-458`).
- A model that instead points at `getCommand`'s own dispatch
  (`t_string.c:475-477` → `461` → `467`) as "the SET WRONGTYPE site" has
  found the *GET command's* path, not SET's — even though it is literally
  the same line of code as Chain A step 4. The distinguishing fact is the
  caller (`setGenericCommand:100` vs. `getCommand:476`), not the callee.
- Similarly, any `checkType`/`addReplyError` call site in `t_list.c`,
  `t_hash.c`, `t_set.c`, `t_zset.c` (e.g. LPUSH's own type check) is a
  different command's WRONGTYPE and must not be substituted for SET's.

## Scoring rubric (0-3)

- **3** — Names `checkType()` (`src/object.c:884`, error text constructed via
  `addReplyErrorObject(c,shared.wrongtypeerr)` at `src/object.c:887`) **and**
  correctly traces a call site that is reached specifically from
  `setCommand`/`setGenericCommand` — either Chain A (`t_string.c:99-101` →
  `getGenericCommand` → `t_string.c:467`, via the `GET` option) or Chain B
  (`t_string.c:117-119`, via `IFEQ`/`IFNE`/`IFDEQ`/`IFDNE`) — and notes (or
  correctly implies) that plain `SET key value` with no such option does
  **not** WRONGTYPE-check at all (it overwrites unconditionally). Either
  chain alone is sufficient for full credit; bonus rigor if both are named.
- **2** — Correctly names `checkType()` in `object.c` as the actual
  construction site and correctly identifies one of the two SET-reachable
  call sites (Chain A or B), but does not address why plain `SET` on an
  existing key normally does *not* WRONGTYPE (i.e. misses that this is a
  conditional/option-gated branch, potentially implying every SET
  type-checks).
- **1** — Finds *some* `checkType()`/WRONGTYPE call site inside
  `t_string.c` but cannot say which SET call path reaches it (e.g. just says
  "there's a checkType call somewhere in t_string.c" without chain evidence),
  or correctly finds `object.c:887` as the reply-construction line but
  attributes it generically to "the type-check helper" without tying it back
  to SET's call sites at all.
- **0** — Names a WRONGTYPE check belonging to a *different* command as if
  it were SET's — e.g. cites `getCommand`'s dispatch (`t_string.c:475-477`)
  or `getexCommand` (`t_string.c:511`) as "SET's WRONGTYPE check" without
  noticing it's actually reached from GET/GETEX, or points at an unrelated
  command entirely (e.g. LPUSH's/HSET's own `checkType` call in
  `t_list.c`/`t_hash.c`), or fabricates a WRONGTYPE check that doesn't exist
  in the code (e.g. claims plain `SET` always type-checks against the
  existing key).

### What a wrong-command answer looks like (for calibration)

- "SET's WRONGTYPE error is constructed in `getGenericCommand` at
  `t_string.c:467`" stated with no mention of `setGenericCommand:99-101`
  calling into it — this is indistinguishable from just describing GET's
  own path and happens to be right only by coincidence of shared code; it
  should score low unless the SET-specific call site (line 100) is named.
- "SET always type-checks the existing key before overwriting, e.g. `SET
  mylist newval` on an existing list returns WRONGTYPE" — this is false;
  per `src/commands/set.json`, plain SET "ignores its type" and always
  overwrites. Only the `GET`/`IFEQ`-family option paths type-check.
