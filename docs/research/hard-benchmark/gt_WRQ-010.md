# GT WRQ-010: switch-based encoding dispatch (core types) vs. moduleTypeMethods ops-table (modules)

**Category**: callback-indirect | **Difficulty**: L3

## Question (verbatim)

> redis object types (e.g. OBJ_ENCODING_* handling in t_string.c / object.c) dispatch on
> obj->encoding via switch statements rather than a function-pointer ops table. Confirm
> whether redis's string type uses any function-pointer dispatch table (like
> moduleTypeMethods) versus wpa's ops-table pattern, and explain the difference in
> indirection style found.

This is a conceptual/comparative question, not an enumeration. It is a deliberate trap for
false-positive hallucination: a naive tool tuned to "find function-pointer dispatch tables"
may fabricate a fake ops-table for `OBJ_ENCODING_*`/string dispatch because that is the
pattern it was built to detect. The correct answer must say plainly: **the core built-in
types (string, list, hash, set, zset, stream) do NOT use a function-pointer ops table — they
use switch/if-else dispatch on `o->encoding` or `o->type`, resolved at compile time to direct
calls.** A real function-pointer ops table (`moduleType` / `RedisModuleTypeMethods`) does
exist in this codebase, but it is scoped **only** to Redis Modules' user-defined data types
(`OBJ_MODULE`), not to any core type including string.

## Method

1. Grepped `object.c` and `t_string.c`/`t_list.c`/`t_hash.c` for `switch` on `->encoding` /
   `->type` and for `OBJ_ENCODING_*` usage, to confirm the switch/if-based dispatch pattern.
2. Grepped for `moduleTypeMethods` / `RedisModuleTypeMethods` (case-insensitive; the literal
   lowercase `moduleTypeMethods` symbol referenced in the question does not exist verbatim —
   the real names are `RedisModuleTypeMethods` in the public module API header and `moduleType`
   in `server.h`) to find and confirm the actual ops-table struct and its call sites.
3. Traced how a per-type `free`/`rdb_load`/etc. function pointer gets populated (module
   registration path) and how it gets invoked (object-free path), to confirm it is a genuine
   indirect call, and confirm it is reached only for `OBJ_MODULE`-typed objects, never for
   `OBJ_STRING`/list/hash/set/zset.
4. Checked for build-system gating: `RedisModuleTypeMethods` and `moduleType` are compiled
   unconditionally (not under any module-support `#ifdef`/build flag) in this checkout —
   Redis Modules support is a core, always-built feature of the server binary, not an optional
   subsystem excluded by default build config. No build-system-level exclusion applies to
   either side of this comparison.

## Part A — Core object/string dispatch is switch/if-based, NOT a function-pointer table

Confirmed switch-on-encoding (or switch-on-type) dispatch at these sites in
`redis/src/object.c`:

| File:Line | Function | Dispatches on |
|---|---|---|
| `object.c:434` | `dupStringObject()` | `switch(o->encoding)` — `OBJ_ENCODING_RAW` / `_EMBSTR` / `_INT` |
| `object.c:550` | `freeStringObject()` | `if (o->encoding == OBJ_ENCODING_RAW)` (if-based, not switch, but same non-indirect style) |
| `object.c:567` | `freeSetObject()` | `switch (o->encoding)` — `OBJ_ENCODING_HT` / `_INTSET` / `_LISTPACK` |
| `object.c:586` | `freeZsetObject()` | `switch (o->encoding)` — `OBJ_ENCODING_SKIPLIST` / `_LISTPACK` |
| `object.c:1290` | `strEncoding()` | `switch(encoding)` — maps every `OBJ_ENCODING_*` to a string name |
| `object.c:643-681` | `decrRefCount()` | `switch(o->type)` — `OBJ_STRING`/`OBJ_LIST`/`OBJ_SET`/`OBJ_ZSET`/`OBJ_HASH`/`OBJ_MODULE`/`OBJ_STREAM`/... each case calls a **statically named** free function (`freeStringObject`, `freeListObject`, ..., `freeModuleObject`) — direct calls resolved at link time, not through a per-object function-pointer field |
| `t_list.c:452` | list dup helper | `switch (o->encoding)` — `OBJ_ENCODING_LISTPACK` / `_QUICKLIST` |
| `t_hash.c:2078` | `hashTypeFree()` | `switch (o->encoding)` — `OBJ_ENCODING_HT` / ... |

`t_string.c` itself has **no `switch` on encoding at all** — it uses scattered `if
(o->encoding == OBJ_ENCODING_INT)` checks (e.g. lines 663, 917, 1315, 1655) for fast-path
optimizations (e.g. skip re-parsing an already-integer-encoded value), not for full
type-dispatch; the exhaustive switch-based dispatch for string encoding lives in `object.c`
(`dupStringObject`, `freeStringObject`, `strEncoding`), not in `t_string.c`.

None of this is indirection: every branch is a compile-time-resolved call to a named
function. There is no `robj`-level or `encoding`-level struct-of-function-pointers analogous
to `wpa_driver_ops`/`wpa_supplicant`'s driver ops table.

## Part B — moduleType / RedisModuleTypeMethods IS a real function-pointer ops table (modules only)

- **Public API struct** `RedisModuleTypeMethods`, defined in `redis/src/redismodule.h:1051-1071`,
  contains genuine function-pointer fields set by module authors:
  `rdb_load`, `rdb_save`, `aof_rewrite`, `mem_usage`, `digest`, `free`, `aux_load`,
  `aux_save`, `free_effort`, `unlink`, `copy`, `defrag`, `mem_usage2`, `free_effort2`,
  `unlink2`, `copy2`, `aux_save2` — all typed as `RedisModuleType*Func` function-pointer
  typedefs (e.g. `typedef void (*RedisModuleTypeFreeFunc)(void *value);`).
- **Internal runtime struct** `moduleType`, defined in `redis/src/server.h:955-975`, mirrors
  the same set of function-pointer fields (`rdb_load`, `rdb_save`, `aof_rewrite`, `mem_usage`,
  `digest`, `free`, `free_effort`, `unlink`, `copy`, `defrag`, `aux_load`, `aux_save`,
  `mem_usage2`, `free_effort2`, `unlink2`, `copy2`, `aux_save2`) plus an `entity` (module type
  ID/name).
- **Population site**: `RM_CreateDataType()` (`redis/src/module.c:7527-7596`) copies each
  function pointer from the caller-supplied `RedisModuleTypeMethods` blob into a freshly
  allocated `moduleType *mt` (e.g. `mt->free = tms->free;`, `mt->rdb_load = tms->rdb_load;`),
  versioned so newer method-set fields are only copied if the module declares a high enough
  `version`.
- **Invocation site (the actual indirect call)**: `freeModuleObject()`
  (`redis/src/object.c:605-609`):
  ```c
  void freeModuleObject(robj *o) {
      moduleValue *mv = o->ptr;
      mv->type->free(mv->value);   // genuine function-pointer call through mv->type
      zfree(mv);
  }
  ```
  `mv->type` is a `moduleType *`; `mv->type->free(...)` is a true indirect call through a
  struct field, exactly analogous to `wpa_driver_ops`'s `ops->set_key(...)` style dispatch.
- **Scope confirmation — modules only**: `freeModuleObject()` is reached exclusively via the
  `case OBJ_MODULE: freeModuleObject(o); break;` arm of the `switch(o->type)` in
  `decrRefCount()` (`object.c:678`). `OBJ_MODULE` is defined as `#define OBJ_MODULE 5` in
  `server.h:877`, a distinct object type from `OBJ_STRING` (0), `OBJ_LIST`, `OBJ_SET`,
  `OBJ_ZSET`, `OBJ_HASH`. No core type's free/dup/digest path ever dereferences a
  `moduleType*`; only values created via the Modules API (`RM_CreateDataType` /
  `RM_ModuleTypeSetValue`) carry a `moduleValue{ moduleType *type; void *value; }` wrapper
  with a populated `type` pointer.

## Definitive answer

Redis's core built-in object/string type dispatch (`object.c`, `t_string.c`, and the other
`t_*.c` files) is **entirely switch/if-else based on `o->encoding` or `o->type`**, resolving
to direct, statically-named function calls at compile/link time — there is **no**
function-pointer ops table for string/list/hash/set/zset. A genuine function-pointer
dispatch table analogous to wpa_supplicant's driver-ops pattern **does exist** in this
codebase, but it is `moduleType`/`RedisModuleTypeMethods` (`server.h:955-975`,
`redismodule.h:1051-1071`, populated in `module.c:7527` `RM_CreateDataType()`, invoked via
`mv->type->free(...)` in `object.c:605` `freeModuleObject()`), and it applies **only** to
values created through the Redis Modules API (`OBJ_MODULE`) — never to the built-in string,
list, hash, set, or sorted-set types. The two subsystems use fundamentally different
indirection styles: core types resolve dispatch statically via `switch`/`if` (zero runtime
indirection, branch predictor can speculate, and the target function is visible to the
compiler for inlining/whole-program analysis), while module types resolve dispatch
dynamically via a struct-of-function-pointers populated at module-load time (the target
function is opaque to the compiler and only known at runtime, same category of indirection
as wpa's `wpa_driver_ops`).

## Scoring rubric (0-3)

- **3**: Correctly states core string/object type dispatch (`t_string.c`/`object.c`, and by
  extension list/hash/set/zset) uses switch/if-else on `->encoding`/`->type` with NO
  function-pointer ops table — AND correctly identifies the real ops table
  (`moduleType`/`RedisModuleTypeMethods`) with reasonable evidence (definition location,
  e.g. `server.h` and/or `redismodule.h`, and/or the `mv->type->free(...)`-style indirect
  call in `object.c`) — AND explicitly scopes that table to Modules/`OBJ_MODULE` only, not
  to core types. Does not need every line number cited above, but must get the core
  distinction and both halves of the comparison correct.
- **2**: Correctly says core string/object dispatch has no function-pointer table (does not
  fabricate one) AND mentions that a real module-type ops table exists somewhere in Redis,
  but is vague/wrong on specifics (e.g. can't name `moduleType`/`RedisModuleTypeMethods`,
  no file evidence, or mildly conflates where module dispatch is invoked), or gets the
  scoping slightly wrong (implies it also touches some core type) without being flatly wrong.
- **1**: Correctly says there is no function-pointer table for core string/object dispatch,
  but fails to find/mention the real `moduleTypeMethods`-equivalent table at all (misses
  Part B entirely) — i.e., answers half the question. Also scores 1 if it fabricates a fake
  ops-table for core string/object dispatch (the exact hallucination this question is
  designed to catch) even if it separately, correctly, also mentions modules.
- **0**: Fabricates a fake function-pointer/vtable dispatch mechanism for
  `OBJ_ENCODING_*`/core string/object type handling (e.g. inventing a
  `stringTypeOps`/`objectTypeMethods`-style table that doesn't exist), and/or asserts Redis
  has no function-pointer dispatch anywhere (missing the real module ops table entirely
  while also getting the core-type claim wrong), or gives an answer with no meaningful file
  evidence for either half.
