# GT WRQ-014: `#ifdef USE_JEMALLOC` / `#ifdef HAVE_BACKTRACE` inventory (redis, kconfig-build, L2)

Question (verbatim): "Find every place in the redis source tree gated by `#ifdef
USE_JEMALLOC` or `#ifdef HAVE_BACKTRACE`, and report which SUBSYSTEM each belongs
to (memory allocator vs crash/debug reporting)."

Method: `grep -rn "USE_JEMALLOC" src/` and `grep -rn "HAVE_BACKTRACE" src/` against
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/redis`, then read every hit's
surrounding code (not filename-guessed) to classify subsystem, plus a manual read
of `src/Makefile` (the `ifeq ($(MALLOC),jemalloc)` block) and `src/config.h` (the
`HAVE_BACKTRACE` definition) for build-system-level effects.

Scope note: the question says "redis source tree", i.e. `src/`. A `.github/workflows/daily.yml`
CI file also passes `USE_JEMALLOC=no`/`USE_JEMALLOC` as a make override — that's CI
config, not source, and doesn't add new information (it just exercises the
Makefile mechanism below), so it is out of scope and not required for a correct
answer, but isn't wrong to mention in passing.

## Part A — `#ifdef USE_JEMALLOC` (memory allocator subsystem)

All 15 non-Makefile files below are the **memory allocator subsystem** — every
site is jemalloc-specific allocation/tuning/introspection code (tcache flush,
arena purge, `je_mallctl`, `je_malloc_stats_print`, allocation-size optimization,
madvise dontneed, Lua's allocator hookup, memory-overcommit diagnostics). None of
them are crash/debug reporting.

| File | Gate kind | What it does (subsystem: memory allocator) |
|---|---|---|
| `src/zmalloc.c` | in-file `#if/#ifdef`, multiple (L65, 309, 359, 637, 693, 897) | Core allocator wrapper: redefines `malloc/calloc/realloc/free` to `je_*`, jemalloc fragmentation-stats helpers, `zfree_with_size` using `je_sdallocx` |
| `src/zmalloc.h` | in-file `#if/#elif`, multiple (L31, 82, 89, 135, 141) | `ZMALLOC_LIB` version string, `zmalloc_size`→`je_malloc_usable_size`, declares `*_with_flags` variants, defrag-hint macros |
| `src/sds.c` | in-file `#if defined`, multiple (L403, 1519, 1527, 1535, 1543, 1551) | `sdsResize`: avoid a realloc when `je_nallocx` says the size class is unchanged; rest are test-suite assertions on jemalloc-specific size-class rounding |
| `src/object.c` | in-file `#if defined(USE_JEMALLOC) && defined(__linux__)` (L864); `#if defined` (L1943) | `dismissObject`: `madvise(MADV_DONTNEED)` path only meaningful under jemalloc+Linux; `OBJECT MALLOC-STATS` command calls `je_malloc_stats_print` |
| `src/db.c` | in-file `#if defined`, x2 (L1232, 1371) | `emptyDbAsync`/flush paths: flush jemalloc thread-cache + force arena purge synchronously after FLUSHDB/FLUSHALL so freed pages are returned promptly |
| `src/lazyfree.c` | in-file `#if defined` (L73) | After async free of two rax/kvstore structures: `je_mallctl("thread.tcache.flush",...)` + `jemalloc_purge()` |
| `src/cluster_asm.c` | in-file `#if defined` (L3746) | End of an active-slot-trim job: `jemalloc_purge()` to return memory after bulk key removal |
| `src/eval.c` | in-file `#if defined`, x3 (L21, 266, 275) | Lua scripting: conditionally includes jemalloc's `<lstate.h>`; on interpreter teardown, destroys the private jemalloc tcache used by that Lua state |
| `src/function_lua.c` | in-file `#if defined`, x3 (L27, 196, 206) | Same pattern as eval.c but for the Functions/Lua engine's own Lua state teardown |
| `src/script.c` | in-file `#if defined` (L67) | Defines `luaAlloc`, the custom Lua allocator callback that routes Lua's malloc/realloc/free through jemalloc `mallocx`/`rallocx` with a per-script/thread arena+tcache, when jemalloc is present |
| `src/syscheck.c` | in-file `#if defined` (L135) | Startup memory-overcommit check: appends a jemalloc-specific caveat to the warning message about `vm.overcommit_memory` |
| `src/server.c` | in-file `#if defined(USE_JEMALLOC) && defined(__linux__)` (L7609) | Dismissing replication-buffer memory via `madvise(MADV_DONTNEED)`, jemalloc+Linux only (mirrors object.c:864) |
| `src/debug.c` | in-file `#ifdef`, x3 (L349, 460, 1104) | **`mallctl_int`/`mallctl_string` helpers plus the `DEBUG MALLCTL`/`DEBUG MALLCTL-STR` sub-commands** — these live in debug.c but are memory-allocator tuning knobs exposed through the DEBUG command surface, *not* crash reporting. (Important: debug.c is a mixed file — see Part B for its unrelated `HAVE_BACKTRACE` gates.) |
| `src/Makefile` | **build-system gate**, not source `#ifdef` | See "Build-system effect" below |

### Build-system-level effect (USE_JEMALLOC) — do not miss this

`src/Makefile` has real `ifeq` blocks, not just source-level `#ifdef`s:

```
Line 84/102:  MALLOC=jemalloc   (default on Linux, or when USE_JEMALLOC=yes)
Line 105-106: ifeq ($(USE_JEMALLOC),no) → MALLOC=libc
Line 301-305: ifeq ($(MALLOC),jemalloc)
                  DEPENDENCY_TARGETS += jemalloc          # builds deps/jemalloc as a sub-make target
                  FINAL_CFLAGS += -DUSE_JEMALLOC -I../deps/jemalloc/include
                  FINAL_LIBS := ../deps/jemalloc/lib/libjemalloc.a $(FINAL_LIBS)
```

So `USE_JEMALLOC` is not only a `#define` consumed by `#ifdef`s in the .c files
above — it also (a) decides whether `make` recurses into `deps/jemalloc` and
compiles the **entire third-party jemalloc library** as a dependency target, and
(b) decides whether `-DUSE_JEMALLOC` is even added to `FINAL_CFLAGS` in the first
place (i.e. it's the switch that makes all the in-file `#ifdef`s above compile
their jemalloc branch instead of the `#else`/absent branch), and (c) whether
`libjemalloc.a` gets linked into the final `redis-server` binary at all. This is
a genuine build-system-level effect distinct from any single in-file `#ifdef`
branch — a correct answer should mention it, not just list the .c/.h `#ifdef`
sites. Note it is **not** "conditionally compile one extra redis `.c` file into
`REDIS_SERVER_OBJ`" (that list, line 387, is static regardless of `MALLOC`) —
the effect is at the whole-external-dependency level, which is arguably a
bigger effect than a single source file.

## Part B — `#ifdef HAVE_BACKTRACE` (crash/debug reporting subsystem)

Every single occurrence of `HAVE_BACKTRACE` in `src/` is in **one file**,
`src/debug.c`, and every one of them is the **crash/debug reporting subsystem**:
signal handlers for SIGSEGV/SIGBUS/SIGALRM, `logStackTrace`, watchdog, EIP/
instruction-pointer inspection (`getAndSetMcontextEip`, `dumpCodeAroundEIP`),
and the stacktrace pipe used by the crash-log writer. Lines: 35, 42, 1260, 1381,
1408, 2079, 2101, 2111, 2258, 2564, 2598, 2752, 2766, 2818, 2958.

There is **no** Makefile-level `ifeq`/`ifdef` for `HAVE_BACKTRACE` — unlike
`USE_JEMALLOC`, it is not a user-facing `make` variable. It is defined purely at
the source level in `src/config.h:72`, itself gated by a platform/libc detection
`#if`:

```c
#if defined(__APPLE__) || (defined(__linux__) && defined(__GLIBC__)) || \
    defined(__FreeBSD__) || ((defined(__OpenBSD__) || defined(__NetBSD__) || defined(__sun)) && defined(USE_BACKTRACE))\
 || defined(__DragonFly__) || (defined(__UCLIBC__) && defined(__UCLIBC_HAS_BACKTRACE__))
#define HAVE_BACKTRACE 1
#endif
```

So `HAVE_BACKTRACE` has a build/platform-dependent origin (it's off on e.g. musl/
uClibc-without-backtrace, or OpenBSD/NetBSD/Solaris unless `USE_BACKTRACE` is
also defined) but there is no separate Makefile conditional-compilation block to
report the way there is for `USE_JEMALLOC` — an answer is not wrong for not
finding one, but would be wrong if it claimed one exists, or if it claimed
`HAVE_BACKTRACE` is set via `-DHAVE_BACKTRACE` in `src/Makefile` (it is not —
check `src/Makefile` for `HAVE_BACKTRACE`: no hits).

## Summary table

| Macro | Files touched (src/) | # in-file sites | Build-system (Makefile) gate? | Subsystem |
|---|---|---|---|---|
| `USE_JEMALLOC` | zmalloc.c, zmalloc.h, sds.c, object.c, db.c, lazyfree.c, cluster_asm.c, eval.c, function_lua.c, script.c, syscheck.c, server.c, debug.c (13 files) | ~30 | **Yes** — `src/Makefile` L84-106, L301-305: controls whether `deps/jemalloc` is built and linked, and whether `-DUSE_JEMALLOC` is defined at all | Memory allocator |
| `HAVE_BACKTRACE` | debug.c (1 file) | 15 | No Makefile block; defined via platform detection in `src/config.h:72` | Crash/debug reporting |

## Scoring rubric (0-3)

- **Score 3**: Lists (or clearly groups) all/nearly-all of the ~13 USE_JEMALLOC
  files AND correctly identifies debug.c as gated by *both* macros for *two
  different, unrelated reasons* (MALLCTL commands = allocator; everything else
  in debug.c = crash reporting) — i.e. doesn't lump debug.c into one subsystem
  by filename alone. AND explicitly calls out the `src/Makefile`
  `ifeq ($(MALLOC),jemalloc)` block as a build-system-level effect (building/
  linking the external jemalloc dependency), not just the in-file `#ifdef`s.
  Correctly notes HAVE_BACKTRACE has no analogous Makefile block.
- **Score 2**: Correctly classifies most files (allocator tuning/purge/tcache
  code vs. debug.c's signal-handler/backtrace code) but misses either (a) the
  Makefile build-system effect for USE_JEMALLOC, or (b) the debug.c dual-gate
  nuance (treats debug.c as purely "crash reporting" and doesn't notice its
  three separate USE_JEMALLOC MALLCTL blocks, or vice versa).
- **Score 1**: Finds the two macros only in debug.c (or only via a shallow grep
  of a couple of files) and describes the general idea (jemalloc = allocator,
  backtrace = crash) without an actual file inventory; or misses most of the 13
  USE_JEMALLOC files (e.g. only finds zmalloc.c/zmalloc.h).
- **Score 0**: Wrong subsystem classification (e.g. calls HAVE_BACKTRACE part of
  the allocator, or claims USE_JEMALLOC conditionally compiles/excludes a redis
  `.c` file from `REDIS_SERVER_OBJ` — it does not, that object list is static),
  or fabricates a Makefile conditional for HAVE_BACKTRACE that doesn't exist.
