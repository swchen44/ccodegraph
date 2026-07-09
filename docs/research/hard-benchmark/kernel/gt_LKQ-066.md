# GT — LKQ-066 (dataflow-lifetime, L3)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`, tag `v6.6`, commit `ffc253263a13`)
**File under test:** `kernel/exit.c`

## Question (verbatim)

> "In kernel/exit.c, list every call site of put_task_struct() (file:line + enclosing function, exact total). Then, for ONE of those sites, trace and show the matching reference acquisition (the get_task_struct() or documented initial reference it releases), with file:line evidence — i.e., demonstrate one complete acquire/release pairing rather than asserting it."

## Part 1 — Enumeration: direct call sites of `put_task_struct()` in kernel/exit.c

**Exact total: 6**

| # | Location | Enclosing function | Call |
|---|----------|--------------------|------|
| 1 | kernel/exit.c:226 | `delayed_put_task_struct()` (defined at line 218) | `put_task_struct(tsk);` |
| 2 | kernel/exit.c:521 | `mm_update_next_owner()` (defined at line 446) | `put_task_struct(c);` — retry path (`c->mm != mm`) |
| 3 | kernel/exit.c:527 | `mm_update_next_owner()` | `put_task_struct(c);` — success path |
| 4 | kernel/exit.c:1117 | `wait_task_zombie()` (defined at line 1099) | `put_task_struct(p);` — WNOWAIT path |
| 5 | kernel/exit.c:1310 | `wait_task_stopped()` (defined at line 1259) | `put_task_struct(p);` |
| 6 | kernel/exit.c:1360 | `wait_task_continued()` (defined at line 1331) | `put_task_struct(p);` |

### Verification (two methods, both = 6)

1. `grep -nE '\bput_task_struct\(' kernel/exit.c` → 6 lines (226, 521, 527, 1117, 1310, 1360).
2. `awk '{n += gsub(/(^|[^A-Za-z0-9_])put_task_struct\(/, "&")} END{print n}' kernel/exit.c` → 6 (counts occurrences, not lines; confirms no line has two calls).

### Known traps / near-misses (NOT direct calls — do not count)

- **kernel/exit.c:218** — `static void delayed_put_task_struct(struct rcu_head *rhp)`: the substring `put_task_struct(` appears inside the *definition* of `delayed_put_task_struct`. A naive `grep -c "put_task_struct("` returns **7** because of this line. Counting 7 is wrong.
- **kernel/exit.c:232** — `call_rcu(&task->rcu, delayed_put_task_struct);` — function-pointer reference to a *different* function, not a call of `put_task_struct`.
- **kernel/exit.c:282** — `put_task_struct_rcu_user(p);` in `release_task()` — different symbol (decrements `task->rcu_users`, not `task->usage`).
- **kernel/exit.c:229** — definition of `put_task_struct_rcu_user()` — different symbol.

An answer that lists the 6 sites and *additionally* mentions 232/282 as related-but-distinct is fine (even better); an answer that counts them in the total is wrong.

Note: sites #2 and #3 (`mm_update_next_owner`) are inside `#ifdef CONFIG_MEMCG` (kernel/exit.c:442–529). Source-level enumeration must still include them; mentioning the ifdef is a bonus, omitting them is an enumeration error.

## Part 2 — One fully evidenced acquire/release pairing

### Primary GT pairing: `wait_task_stopped()` — acquire :1303 → release :1310

**Acquire** — kernel/exit.c:1303, with the kernel's own comment explaining exactly why the reference is taken (kernel/exit.c:1296–1303):

```c
	/*
	 * Now we are pretty sure this task is interesting.
	 * Make sure it doesn't get reaped out from under us while we
	 * give up the lock and then examine it below.  We don't want to
	 * keep holding onto the tasklist_lock while we call getrusage and
	 * possibly take page faults for user memory.
	 */
	get_task_struct(p);
```

**Connecting path** (straight-line, same function, same variable `p`, no early exits between acquire and release) — kernel/exit.c:1303–1310:

```c
	get_task_struct(p);                       // :1303  acquire (usage++)
	pid = task_pid_vnr(p);
	why = ptrace ? CLD_TRAPPED : CLD_STOPPED;
	read_unlock(&tasklist_lock);              // :1306  lock dropped → ref is what keeps p alive
	sched_annotate_sleep();
	if (wo->wo_rusage)
		getrusage(p, RUSAGE_BOTH, wo->wo_rusage);  // p used after lock drop
	put_task_struct(p);                       // :1310  release (usage--)
```

**Mechanism evidence:** `get_task_struct()` does `refcount_inc(&t->usage)` and `put_task_struct()` does `refcount_dec_and_test(&t->usage)` — include/linux/sched/task.h:113–117 (`get_task_struct`) and include/linux/sched/task.h:123–126 (`put_task_struct`). Same counter (`task->usage`), same task, one inc matched by exactly one dec on every path — this is a complete, non-asserted pairing.

### Acceptable alternate pairings (any ONE, fully cited, earns full credit)

1. **`wait_task_zombie()` WNOWAIT path:** acquire `get_task_struct(p)` at kernel/exit.c:1112 → release at kernel/exit.c:1117. Same straight-line shape (ref taken before `read_unlock(&tasklist_lock)` at :1113, `p` used in `getrusage` at :1116, released at :1117).
2. **`wait_task_continued()`:** acquire `get_task_struct(p)` at kernel/exit.c:1355 → release at kernel/exit.c:1360. Same shape.
3. **`mm_update_next_owner()`:** acquire `get_task_struct(c)` at kernel/exit.c:508 → released at kernel/exit.c:521 (retry path, `c->mm != mm`) **or** kernel/exit.c:527 (success path). One acquire, exactly one of the two releases executes per iteration; the comment at :514–517 ("Delay read_unlock() till we have the task_lock() to ensure that c does not slip away underneath us") documents the intent. A complete answer for this alternate must show that :521 and :527 are mutually exclusive branches of the *same* acquisition at :508.
4. **`delayed_put_task_struct()` at kernel/exit.c:226 — the architectural pairing** (hardest; full credit only with cross-file evidence). The `put_task_struct(tsk)` at :226 releases the task's **initial** `usage` reference, set at fork time:
   - kernel/fork.c:1158 — `refcount_set(&tsk->rcu_users, 2);` with comment (kernel/fork.c:1153–1157): "One for the user space visible state that goes away when reaped. One for the scheduler."
   - kernel/fork.c:1160 — `refcount_set(&tsk->usage, 1);` with comment (kernel/fork.c:1159): "/* One for the rcu users */" — i.e., the initial `usage` ref is *owned by* the `rcu_users` mechanism.
   - The two `rcu_users` refs are dropped at kernel/exit.c:282 (`put_task_struct_rcu_user(p)` in `release_task()`, the "reaped" ref) and kernel/sched/core.c:5289 (`put_task_struct_rcu_user(prev)` in `finish_task_switch()`, the "scheduler" ref).
   - When `rcu_users` hits 0, `put_task_struct_rcu_user()` (kernel/exit.c:231–232) schedules `delayed_put_task_struct` via `call_rcu`; after the grace period, :226 drops that initial `usage` ref from kernel/fork.c:1160.
   - This pairing is **architectural** (initial reference from `dup_task_struct`, not an explicit `get_task_struct` call). It is a valid answer only if the candidate cites the fork.c refcount_set lines/comments; merely asserting ":226 releases the last reference" without the fork.c evidence is an *asserted* pairing (score 2, not 3).

### Classification honesty (per benchmark discipline)

- Sites 2–6 pair with **explicit** `get_task_struct` calls in the same function (kernel/exit.c:508, :1112, :1303, :1355). These are the evidenced, self-contained pairings.
- Site 1 (:226) pairs with the **documented initial reference** (`refcount_set(&tsk->usage, 1)` in `dup_task_struct`, kernel/fork.c:1160) — architectural, cross-file, comment-documented.
- No site in this file is an unpaired release; conversely, "no local get_task_struct near :226" does **not** indicate a bug — the acquire is the fork-time initial reference.

## Question-text check

No flaws found. "put_task_struct()" is unambiguous as a direct-call target; the near-miss symbols (`put_task_struct_rcu_user`, `delayed_put_task_struct`) are clearly distinct identifiers, and the question's "documented initial reference" clause correctly anticipates the :226 architectural case. The question is answerable exactly as posed.

## Rubric (0–3)

- **3** — Exact total **6** with all six file:line + enclosing-function entries correct, AND one genuinely evidenced pairing: both acquire and release cited with file:line, plus the connecting code path or kernel comment shown (the primary pairing or any acceptable alternate above). For the :226 alternate, the kernel/fork.c:1158–1160 evidence is required.
- **2** — Total of 6 with correct sites, but the pairing is asserted rather than evidenced (e.g., "1310 pairs with 1303" with no quoted code/comment or no acquire line cited; or ":226 releases the initial ref" without fork.c evidence). Also 2 if enumeration is perfect but the chosen "pairing" mismatches (e.g., pairs :1310 with :1112).
- **1** — Incomplete or inflated enumeration (e.g., 7 by counting the :218 definition substring, or counting :282's `put_task_struct_rcu_user`, or missing the CONFIG_MEMCG sites :521/:527), regardless of pairing quality; or correct pairing but ≤4 of 6 sites listed.
- **0** — Enumeration substantially wrong (≥3 sites missing/spurious) and no valid pairing.

Grader notes: line numbers must match v6.6 exactly (±0). Listing :232/:282 explicitly as excluded near-misses is a positive signal, not an error. `wait_task_stopped` vs `wait_task_zombie` vs `wait_task_continued` vs `mm_update_next_owner` pairings are all equally acceptable for the "3".
