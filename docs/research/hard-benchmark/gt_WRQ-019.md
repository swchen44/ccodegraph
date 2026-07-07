# GT WRQ-019: shared state between bio.c's background thread(s) and the main thread (redis, locking-rcu, L3)

**Question (verbatim):** "bio.c spawns a background thread via pthread_create for
bioProcessBackgroundJobs. List every piece of shared state (global variables or
struct fields) this background thread reads or writes that the main thread also
touches, and identify what synchronization primitive (if any) protects each."

**Scope limiter to honor exactly:** the question asks for state that (a)
`bioProcessBackgroundJobs` itself reads/writes **and** (b) the main thread
**also** touches. A global that only one side touches does not qualify, even if
it lives in bio.c and looks "shared" at a glance (see Exclusions below — this
is the kind of trap that has burned this benchmark before).

Method: read `src/bio.c` in full (446 lines); located the `pthread_create`
call(s) in `bioInit()` and the full body of `bioProcessBackgroundJobs`
(line 257-369). For every global/static/struct field touched inside that
function, grepped the rest of `bio.c` and the whole `src/` tree for other
touch points to confirm genuine main-thread sharing, then read the enclosing
lock/unlock, cond wait/signal, or atomic macro at each site. Repo:
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/redis`.

## Correction to the question's framing

`bioInit()` (bio.c:171-178) calls `pthread_create` **3 times in a loop**
(`BIO_WORKER_NUM` = 3: close-file, aof-fsync, lazy-free workers), all running
the *same* entry point `bioProcessBackgroundJobs`, distinguished only by the
`worker` id passed as `(void*)j`. So there are 3 background threads, not one —
this matters because it means `bio_jobs`/`bio_mutex`/`bio_newjob_cond` are
really per-worker **arrays**, not single scalars, and the mutex granularity is
per-worker, not one global bio lock.

## Shared state inventory

| # | State | Declared | Touched by bio thread (in `bioProcessBackgroundJobs`) | Touched by main thread | Synchronization |
|---|---|---|---|---|---|
| 1 | `bio_jobs[BIO_WORKER_NUM]` (job queue, `list*`) | bio.c:72 | read/pop: `listLength` bio.c:285, `listFirst` bio.c:290, `listDelNode` bio.c:365 | pushed via `bioSubmitJob` bio.c:185 (`listAddNodeTail`), called from main thread via `bioCreateLazyFreeJob`/`bioCreateCloseJob`/`bioCreateFsyncJob`/`bioCreateCloseAofJob`/`bioCreateCompRq` (see call sites below); also read in `bioDrainWorker` bio.c:387 | `bio_mutex[worker]` — held at bio.c:271/294/364 (bio thread) and bio.c:184-188, 386-390 (main thread) |
| 2 | `bio_jobs_counter[BIO_NUM_OPS]` (per-type pending count) | bio.c:73 | decremented bio.c:366 | incremented in `bioSubmitJob` bio.c:186 (main thread); read in `bioPendingJobsOfType` bio.c:376, called from `aof.c:978`, `server.c:6603`, `evict.c:738` (all main thread) | Same `bio_mutex[worker]` (worker derived consistently from `bio_job_to_worker[type]` on both sides) |
| 3 | `bio_mutex[BIO_WORKER_NUM]` (the mutex itself) | bio.c:70 | locked/unlocked bio.c:271,294,364 | initialized in `bioInit` bio.c:135 (main thread, before threads spawn); locked/unlocked in `bioSubmitJob`, `bioPendingJobsOfType`, `bioDrainWorker` | — (it *is* the primitive protecting #1/#2) |
| 4 | `bio_newjob_cond[BIO_WORKER_NUM]` (condvar) | bio.c:71 | waited on bio.c:286; signaled bio.c:367 | signaled in `bioSubmitJob` bio.c:187 (main thread → wakes bio thread); waited on in `bioDrainWorker` bio.c:388 (main thread waits for bio thread to drain, woken by bio thread's signal at 367) | Paired 1:1 with `bio_mutex[worker]` (standard cond+mutex protocol) |
| 5 | `bio_comp_list` (completion-callback queue, `list*`) | bio.c:78 | appended `listAddNodeTail` bio.c:351 | drained/swapped in `bioPipeReadJobCompList` bio.c:428-430, which runs on the **main thread** via the `ae` event loop (registered on `job_comp_pipe[0]` in `bioInit` bio.c:156-159) | `bio_mutex_comp` — locked bio.c:350/352 (bio thread) and bio.c:427/432 (main thread) |
| 6 | `bio_mutex_comp` (the mutex itself) | bio.c:79 | locked/unlocked bio.c:350,352 | initialized bio.c:142 (main thread); locked/unlocked bio.c:427,432 | — (it *is* the primitive protecting #5) |
| 7 | `job_comp_pipe[2]` (self-pipe, wakes main event loop) | bio.c:80 | written to via `write(job_comp_pipe[1],"A",1)` bio.c:354 | created in `bioInit` bio.c:149 (main thread, before threads spawn); read via `read(fd,...)` bio.c:424 inside `bioPipeReadJobCompList` (main thread, event-loop callback on fd `job_comp_pipe[0]`) | **No mutex.** Safety rests on (a) the fd values being set once in `bioInit` before any bio thread is created (happens-before via `pthread_create`) and never mutated after, and (b) POSIX guaranteeing atomicity of writes ≤`PIPE_BUF` so concurrent 1-byte writes from the 3 bio workers can't interleave-corrupt. This is a genuine "no lock, but safe for a documented kernel-atomicity reason" case, not an oversight. |
| 8 | `server.aof_bio_fsync_status` (`redisAtomic int`, server.h:2309) | server.h:2309 | read+written bio.c:320,321,328 | read/written main thread: `aof.c:1064-1068`, `server.c:2422`, `server.c:5218-5220`, `server.c:6557` | `atomicGet`/`atomicSet` macros (`atomicvar.h`) — **lock-free compiler atomics** (C11 `_Atomic`/`__atomic_load_n`/`__atomic_store_n`, relaxed ordering), **not a mutex** |
| 9 | `server.aof_bio_fsync_errno` (`redisAtomic int`, server.h:2310) | server.h:2310 | written bio.c:322 | read main thread: `server.c:5220` | Same `atomicGet`/`atomicSet` lock-free atomics |
| 10 | `server.fsynced_reploff_pending` (`redisAtomic long long`, server.h:2376) | server.h:2376 | written bio.c:329 | read/written main thread: `aof.c:1028,1161,1346,2898,3147`, `server.c:2050` | Same `atomicGet`/`atomicSet` lock-free atomics — **except** `server.c:2480` (`server.fsynced_reploff_pending = 0;`), a plain non-atomic assignment during `initServer()`, which is safe only because it runs before `bioInit()`/thread creation (single-threaded at that point), not a race |
| 11 | `server.bio_cpulist` (`char*`, server.h:2597) | server.h:2597 | read bio.c:267 (`redisSetCpuAffinity(server.bio_cpulist)`, once at thread startup) | set from config at startup: `config.c:3230`, flagged `IMMUTABLE_CONFIG` (cannot change at runtime) | **None found** — safe only because it's immutable after startup and set before `bioInit()` spawns the threads (happens-before via thread creation); there is no lock guarding it, and none is needed given the immutability contract |

## Exclusions — globals in bio.c that do NOT qualify (the scope-limiter trap)

- **`bio_threads[BIO_WORKER_NUM]`** (bio.c:69): written by `bioInit` and read by
  `bioKillThreads` — both main-thread-only paths. `bioProcessBackgroundJobs`
  itself never references `bio_threads`. Fails "the background thread
  reads/writes it" → excluded.
- **`bio_worker_title[]`** (bio.c:51-55) and **`bio_job_to_worker[]`**
  (bio.c:59-67): `bio_worker_title` is read inside
  `bioProcessBackgroundJobs` (bio.c:265) but is a compile-time-constant string
  table the main thread never touches at runtime → fails "main thread also
  touches it". `bio_job_to_worker` is touched by the main thread
  (`bioSubmitJob`, `bioPendingJobsOfType`, `bioDrainWorker`) but
  `bioProcessBackgroundJobs` never looks it up (the worker id arrives as the
  thread's `arg`) → fails "background thread touches it". Both excluded for
  the opposite reason from `bio_threads`.
- **`errno`**: read at several points in the job-processing branches
  (bio.c:301-334). `errno` is thread-local storage per POSIX/glibc — the bio
  thread's `errno` and the main thread's `errno` are different objects, so
  this is not shared state despite being a familiar "global-looking" symbol.
- **The `bio_job`/`bio_comp_item` payload itself** (fields like
  `job->fd_args.fd`, `job->free_args.free_fn`, `comp_rsp->func`): heap-allocated
  per-job by the producer (main thread) and freed by the consumer (bio
  thread), but ownership is fully handed off under `bio_mutex[worker]` /
  `bio_mutex_comp` during the enqueue/dequeue — at any instant exactly one side
  owns it. Not persistent global/struct-field state in the sense the question
  means, so not scored as a separate item, though describing this
  handoff-under-lock pattern is a sign of a thorough answer.

## Summary of synchronization primitives used

- **Per-worker mutex + condvar** (`bio_mutex[3]` / `bio_newjob_cond[3]`):
  protects the job queues (`bio_jobs[3]`) and per-type pending counters
  (`bio_jobs_counter[7]`).
- **A separate, single global mutex** (`bio_mutex_comp`, *not* part of the
  per-worker array): protects the completion-callback list (`bio_comp_list`),
  shared across all 3 workers.
- **Lock-free atomics** (`atomicGet`/`atomicSet` over `redisAtomic`-qualified
  fields): protect the 3 AOF-fsync status fields on `server`
  (`aof_bio_fsync_status`, `aof_bio_fsync_errno`, `fsynced_reploff_pending`).
- **No synchronization, safe via POSIX pipe-write atomicity +
  happens-before-at-thread-creation**: the `job_comp_pipe` fds themselves.
- **No synchronization, safe via immutability + happens-before-at-thread-creation**:
  `server.bio_cpulist`.

So the draft hint "bio.c uses its own mutex/condvar pair per job type" is
**half right**: it's correct that there's a per-**worker** mutex/condvar pair
(not per individual job type — 7 job types map onto only 3 workers via
`bio_job_to_worker`), but that pair only covers the job queues/counters (#1-4).
The completion-response path uses a **different, single, non-per-worker**
mutex (`bio_mutex_comp`, #5-6), and three more fields are protected by atomics
rather than any mutex at all (#8-10), plus two fields with no lock at all,
justified by other happens-before arguments (#7, #11).

## Scoring rubric (0-3)

- **Score 3**: Identifies all of #1-#4 (job queue + counter, guarded by the
  per-worker `bio_mutex`/`bio_newjob_cond` pair) AND #5-#6 (`bio_comp_list`
  guarded by the *separate* `bio_mutex_comp`, not the per-worker mutex) AND at
  least the AOF-fsync-status atomics (#8-#10, correctly identified as
  lock-free atomics, not a mutex). Explicitly notes that 3 threads are spawned
  (loop over `BIO_WORKER_NUM`), not one. Does not need to catch #7/#11 (the
  two "no lock, safe for other reasons" items) for full credit, but bonus if
  it does. Does not incorrectly include excluded items (`bio_threads`,
  `bio_worker_title`, `bio_job_to_worker`, `errno`) as "shared and
  synchronized by X" — including them with a plausible-sounding but wrong
  synchronization claim is a correctness error, not just an omission.
- **Score 2**: Correctly finds the job-queue/counter pair (#1-#4) and its
  per-worker mutex/condvar, but either misses that the completion list
  (#5-#6) uses a *different* mutex than the job queues (e.g. claims a single
  global bio mutex protects everything), or misses/mischaracterizes the
  atomic-protected `server.*` fields (#8-#10) as being protected by a mutex
  instead of lock-free atomics, or vice versa.
- **Score 1**: Finds only the job queue (#1) and generically says "a mutex
  protects it" without identifying it's per-worker (3 mutexes, not 1), and
  doesn't mention the completion-response path or the AOF-fsync atomic fields
  at all.
- **Score 0**: Claims there's only one thread when 3 are spawned as if it
  were architecturally material and gets the queue analysis wrong as a
  result; or claims the job queue is unsynchronized/racy (it is correctly
  mutex-protected); or claims `server.aof_bio_fsync_status`/`errno`/
  `bio_cpulist` are protected by `bio_mutex` (wrong primitive/wrong scope);
  or lists `bio_threads`/`bio_worker_title` as shared+synchronized state
  (fails the question's own "main thread also touches" / "background thread
  touches" scope limiter).

### Call sites confirming main-thread sharing (for the job-queue/counter path)

`bioCreateLazyFreeJob` ← `lazyfree.c:234,346,355,367,378,388,401`
`bioCreateCloseJob` ← `replication.c:237,1744,2631`, `aof.c:1776`, `rdb.c:4537`
`bioCreateCloseAofJob`/`bioCreateFsyncJob` ← `aof.c:984,989`
`bioCreateCompRq` ← `cluster_asm.c:3180`, `db.c:1368`
`bioPendingJobsOfType` ← `aof.c:978`, `server.c:6603`, `evict.c:738`
`bioDrainWorker` ← `aof.c:2894`, `config.c:2688`

All of these run on the main (event-loop) thread in normal operation.
