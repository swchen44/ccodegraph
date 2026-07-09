# GT — LKQ-073 (locking-rcu, L3)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`, tag `v6.6`, Makefile VERSION=6 PATCHLEVEL=6 SUBLEVEL=0)

## Question (verbatim)

> Identify the per-runqueue lock field inside struct rq (kernel/sched/sched.h): field name + line. Give the primary helper functions used to take/release it in v6.6 (names + definition file:line) — report what the source actually shows, which may differ from older kernels' plain spin_lock usage. Then give two real call sites in kernel/sched/core.c that acquire this lock (file:line each).

## Ground truth

### The lock field

`struct rq` begins at **kernel/sched/sched.h:962**. The lock field is:

```c
962	struct rq {
963		/* runqueue lock: */
964		raw_spinlock_t		__lock;
```

**Field name: `__lock` (type `raw_spinlock_t`), kernel/sched/sched.h:964.**

The double-underscore name is deliberate (renamed from `lock` in the v5.14 core-scheduling series) so that no code touches the field directly; all access goes through the `rq_lockp()`/`raw_spin_rq_*()` accessor family below. **There is no `raw_spinlock_t lock;` field in v6.6's struct rq.**

### Helper functions (definition sites verified in source)

| Helper | Definition site | Notes |
|---|---|---|
| `rq_lockp(struct rq *rq)` | **kernel/sched/sched.h:1235** (CONFIG_SCHED_CORE) / **sched.h:1333** (!CONFIG_SCHED_CORE) | static inline. SCHED_CORE version: `if (sched_core_enabled(rq)) return &rq->core->__lock; return &rq->__lock;` — the core-scheduling dimension: when core sched is enabled the *core leader's* `__lock` is shared by all SMT siblings. Non-core version just returns `&rq->__lock`. Comment above it (sched.h:1231–1234) warns the return value isn't stable "unless you actually hold a relevant rq->__lock". |
| `__rq_lockp(struct rq *rq)` | **kernel/sched/sched.h:1243** (CONFIG_SCHED_CORE, tests `rq->core_enabled`) / **sched.h:1338** (!CONFIG_SCHED_CORE) | static inline; static_branch-free variant used inside the retry loops and lockdep asserts. |
| `raw_spin_rq_lock_nested(struct rq *rq, int subclass)` | **kernel/sched/core.c:551** | The real acquire primitive. Loops: `lock = __rq_lockp(rq); raw_spin_lock_nested(lock, subclass);` and re-checks `lock == __rq_lockp(rq)` (the lock pointer can change under core-sched enable/disable). Extern-declared at sched.h:1366. |
| `raw_spin_rq_lock(struct rq *rq)` | **kernel/sched/sched.h:1370** | static inline; just `raw_spin_rq_lock_nested(rq, 0);`. (Note: defined in sched.h, not core.c.) |
| `raw_spin_rq_trylock(struct rq *rq)` | **kernel/sched/core.c:576** | Same retry pattern with `raw_spin_trylock`. Extern-declared at sched.h:1367. |
| `raw_spin_rq_unlock(struct rq *rq)` | **kernel/sched/core.c:600** | Body (core.c:602): `raw_spin_unlock(rq_lockp(rq));`. Extern-declared at sched.h:1368. |
| `raw_spin_rq_lock_irq` / `raw_spin_rq_unlock_irq` | **kernel/sched/sched.h:1375 / 1381** | static inlines wrapping local_irq_disable/enable around the above. |
| `_raw_spin_rq_lock_irqsave` / `raw_spin_rq_unlock_irqrestore` / `raw_spin_rq_lock_irqsave` macro | **kernel/sched/sched.h:1387 / 1395 / 1401** | irqsave/irqrestore variants. |
| `rq_lock` / `rq_lock_irq` / `rq_lock_irqsave` | **kernel/sched/sched.h:1678 / 1670 / 1662** (each preceded by `static inline void` on the line above: 1677/1669/1661) | The wrapper family most scheduler code uses: acquires via `raw_spin_rq_lock*()` then `rq_pin_lock(rq, rf)` (rq_flags pinning for lockdep/clock tracking). |
| `rq_unlock` / `rq_unlock_irq` / `rq_unlock_irqrestore` | **kernel/sched/sched.h:1702 / 1694 / 1686** | `rq_unpin_lock()` then `raw_spin_rq_unlock*()`. |
| (bonus) `DEFINE_LOCK_GUARD_1(rq_lock, ...)` guards | kernel/sched/sched.h:1709 ff. | v6.6 also defines scoped-guard forms (`rq_lock`, `rq_lock_irq`, `rq_lock_irqsave` guards). |
| (bonus) `lockdep_assert_rq_held(struct rq *rq)` | kernel/sched/sched.h:1361 | `lockdep_assert_held(__rq_lockp(rq));` |

**CONFIG_SCHED_CORE dimension (must-mention for full helper credit at L3, or at least the `rq_lockp` indirection):** under `#ifdef CONFIG_SCHED_CORE` (sched.h:1235/1243), `rq_lockp()` returns `&rq->core->__lock` when core scheduling is enabled, so sibling runqueues of one SMT core share a single lock; `raw_spin_rq_lock_nested()`/`raw_spin_rq_trylock()` therefore re-check `__rq_lockp(rq)` after acquiring in case the pointer changed. The `#else` variants (sched.h:1333/1338) return `&rq->__lock` unconditionally.

### Acceptable acquisition call sites in kernel/sched/core.c (any two suffice; all verified)

| # | file:line | Code | Enclosing function (def line) |
|---|---|---|---|
| 1 | kernel/sched/core.c:616 | `raw_spin_rq_lock(rq1);` | `double_rq_lock()` (core.c:609) — line 618 `raw_spin_rq_lock_nested(rq2, SINGLE_DEPTH_NESTING);` also acceptable |
| 2 | kernel/sched/core.c:636 | `raw_spin_rq_lock(rq);` | `__task_rq_lock()` (core.c:627) |
| 3 | kernel/sched/core.c:660 | `raw_spin_rq_lock(rq);` | `task_rq_lock()` (core.c:651) |
| 4 | kernel/sched/core.c:1070 | `raw_spin_rq_lock_irqsave(rq, flags);` | `resched_cpu()` (core.c:1065) |
| 5 | kernel/sched/core.c:2601 | `rq_lock(rq, &rf);` | `migration_cpu_stop()` (core.c:2579) |
| 6 | kernel/sched/core.c:2689 | `raw_spin_rq_lock(rq);` | `push_cpu_stop()` (core.c:2683) |
| 7 | kernel/sched/core.c:4027 | `rq_lock(rq, &rf);` | `ttwu_queue()` (core.c:4019) |
| 8 | kernel/sched/core.c:6612 | `rq_lock(rq, &rf);` | `__schedule()` (core.c:6576) — the canonical site, followed by `smp_mb__after_spinlock();` |
| 9 | kernel/sched/core.c:9264 | `raw_spin_rq_lock(rq);` | `init_idle()` (core.c:~9250) |

Any other genuine core.c site that acquires via the `raw_spin_rq_lock*` / `rq_lock*` family is acceptable if file:line and function check out (e.g. rq_lock at core.c:794, 820, 2527, 5652, 9433; rq_lock_irqsave at 3880, 9524, 9681, 9725, 9836, 12037, 12061, 12085; rq_lock_irq at 10900; raw_spin_rq_lock_irqsave at 5085; raw_spin_rq_lock_irq at 6381). Unlock-only sites do not count as "acquire".

### Verification notes

- Only one `struct rq {` definition exists in kernel/sched/sched.h (line 962); `__lock` at 964 is the only lock field for the runqueue itself (grep for `__lock` in sched.h shows only the field plus the accessor bodies).
- `raw_spin_rq_lock_nested` (core.c:551), `raw_spin_rq_trylock` (core.c:576), `raw_spin_rq_unlock` (core.c:600) are the only out-of-line members; everything else in the family is a static inline in sched.h. An answer placing `raw_spin_rq_lock` "in core.c" is a minor slip (it's sched.h:1370) — do not fail it on that alone if the family and mechanism are right.
- Question-text problems: none material. One nuance: the question says "helper functions used to take/release it" singular-file-agnostic — a complete answer spans both core.c and sched.h; graders should not require all helpers to be in one file.
- Stale-memory trap (the point of this question): pre-v5.14 kernels had `raw_spinlock_t lock;` and code did `raw_spin_lock(&rq->lock)` / `raw_spin_lock_irqsave(&rq->lock, flags)` directly. The v5.14 core-scheduling series renamed the field to `__lock` and introduced the `rq_lockp`/`raw_spin_rq_*` accessor layer precisely to break direct access. v6.6 shows only the new scheme.

## Rubric (0–3)

- **3** — Names the field **`__lock`** (`raw_spinlock_t`) at sched.h:964 (±3 lines tolerance), gives the **raw_spin_rq_lock-family helpers** with plausible definition sites (must include at least `raw_spin_rq_lock`/`raw_spin_rq_unlock` or the `rq_lock`/`rq_unlock` wrappers; crediting `raw_spin_rq_lock_nested` core.c:551 and/or `rq_lockp`/`__rq_lockp` with the CONFIG_SCHED_CORE `rq->core->__lock` behavior is expected at L3), **and** two valid core.c acquisition sites from (or equivalent to) the table above with correct file:line.
- **2** — Correct `__lock` field + correct helper family, but call sites missing/wrong lines, or helpers named without definition sites, or CONFIG_SCHED_CORE indirection wholly absent when helper detail is otherwise thin.
- **1** — Field or helpers correct but the rest confabulated; **or** an answer that claims a plain `lock` spinlock field with direct `spin_lock`/`raw_spin_lock(&rq->lock)`/`spin_lock_irqsave` usage while still landing something real (this is the stale-memory failure mode — cap at 1).
- **0** — Wrong field and wrong helpers, fabricated line numbers throughout, or answer about a different struct/lock (e.g. `p->pi_lock`, `rq->wait_lock`).

**Hard cap rule:** any answer asserting the v6.6 field is `lock` (no underscores) or that v6.6 scheduler code takes the rq lock via plain `spin_lock_irqsave(&rq->lock, ...)` scores **at most 1**, regardless of other detail — that is pre-v5.14 knowledge and the question explicitly warns about it.
