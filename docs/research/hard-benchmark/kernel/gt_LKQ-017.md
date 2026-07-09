# GT: LKQ-017 (caller-callee, L2)

## Question (verbatim)

> "List every direct call to wake_up_process() in .c files under kernel/ (recursive, kernel/ subtree only; exclude comments, strings, and other wake_up_* variants). Return the enclosing caller function and file:line for each call site, plus the exact total number of call sites."

Repo: Linux kernel v6.6 (`git describe` = `v6.6`, HEAD `ffc253263` "Linux 6.6") at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`

## Answer

**Exact total: 47 direct call sites** of `wake_up_process()` in `.c` files under `kernel/` (recursive).

Scope facts:
- Raw `grep -rn "wake_up_process(" kernel/ --include='*.c'` = **59** lines.
  Breakdown: 47 real calls + 11 comment hits + 1 function *definition* (kernel/sched/core.c:4476, not a call).
- Word-boundary `grep -rnE '\bwake_up_process\b'` = **62** lines; the 3 extras over method 1 are all
  bare-name (no call parens) references, none of them calls (see "Excluded hits" below).
- **Zero** hits inside string literals.
- **Zero** true function-pointer passes of `wake_up_process` as a callback in this scope. The only bare-name
  in-code reference is `EXPORT_SYMBOL(wake_up_process)` (kernel/sched/core.c:4480) — a macro reference,
  not a call; excluded per the question's "direct call" wording (judgment note below).
- "Other wake_up_* variants" (wake_up_state, wake_up_interruptible, wake_up_q, wake_up_new_task, ...) are
  excluded by construction: both grep patterns match the exact identifier `wake_up_process` only.

## Full enumeration (47 call sites, sorted by path then line)

| # | file:line | Enclosing caller function |
|---|---|---|
| 1 | kernel/audit_tree.c:965 | `audit_schedule_prune` |
| 2 | kernel/bpf/cpumap.c:439 | `__cpu_map_entry_alloc` |
| 3 | kernel/bpf/cpumap.c:748 | `cpu_map_generic_redirect` |
| 4 | kernel/bpf/cpumap.c:763 | `__cpu_map_flush` |
| 5 | kernel/cgroup/freezer.c:168 | `cgroup_freeze_task` |
| 6 | kernel/cpu.c:755 | `__cpuhp_kick_ap` |
| 7 | kernel/dma/map_benchmark.c:137 | `do_map_benchmark` |
| 8 | kernel/exit.c:170 | `__exit_signal` |
| 9 | kernel/exit.c:311 | `rcuwait_wake_up` |
| 10 | kernel/exit.c:760 | `exit_notify` |
| 11 | kernel/hung_task.c:252 | `proc_dohung_task_timeout_secs` |
| 12 | kernel/irq/handle.c:136 | `__irq_wake_thread` |
| 13 | kernel/irq/manage.c:1286 | `wake_up_and_wait_for_irq_thread_ready` |
| 14 | kernel/irq_work.c:36 | `wake_irq_workd` |
| 15 | kernel/kallsyms_selftest.c:465 | `kallsyms_test_init` |
| 16 | kernel/kthread.c:454 | `__kthread_create_on_node` |
| 17 | kernel/kthread.c:664 | `kthread_park` |
| 18 | kernel/kthread.c:708 | `kthread_stop` |
| 19 | kernel/kthread.c:865 | `__kthread_create_worker` |
| 20 | kernel/kthread.c:980 | `kthread_insert_work` |
| 21 | kernel/locking/percpu-rwsem.c:135 | `percpu_rwsem_wake_function` |
| 22 | kernel/locking/semaphore.c:278 | `__up` |
| 23 | kernel/pid.c:146 | `free_pid` |
| 24 | kernel/rcu/tree.c:2430 | `rcu_wake_cond` |
| 25 | kernel/rcu/tree.c:4658 | `rcu_spawn_gp_kthread` |
| 26 | kernel/sched/core.c:1029 | `wake_up_q` |
| 27 | kernel/sched/cpufreq_schedutil.c:625 | `sugov_kthread_create` |
| 28 | kernel/sched/psi.c:1358 | `psi_trigger_create` |
| 29 | kernel/softirq.c:80 | `wakeup_softirqd` |
| 30 | kernel/time/alarmtimer.c:758 | `alarmtimer_nsleep_wakeup` |
| 31 | kernel/time/hrtimer.c:1942 | `hrtimer_wakeup` |
| 32 | kernel/time/posix-cpu-timers.c:597 | `cpu_timer_fire` |
| 33 | kernel/time/timer.c:2094 | `process_timeout` |
| 34 | kernel/torture.c:954 | `_torture_create_kthread` |
| 35 | kernel/trace/ring_buffer_benchmark.c:268 | `ring_buffer_producer` |
| 36 | kernel/trace/ring_buffer_benchmark.c:293 | `ring_buffer_producer` |
| 37 | kernel/trace/ring_buffer_benchmark.c:407 | `ring_buffer_producer_thread` |
| 38 | kernel/trace/trace_hwlat.c:452 | `start_single_kthread` |
| 39 | kernel/trace/trace_osnoise.c:1813 | `timerlat_irq` |
| 40 | kernel/trace/trace_osnoise.c:1819 | `timerlat_irq` |
| 41 | kernel/trace/trace_selftest.c:1238 | `trace_selftest_startup_wakeup` |
| 42 | kernel/vhost_task.c:72 | `vhost_task_wake` |
| 43 | kernel/workqueue.c:1142 | `kick_pool` |
| 44 | kernel/workqueue.c:2224 | `create_worker` |
| 45 | kernel/workqueue.c:2264 | `wake_dying_workers` |
| 46 | kernel/workqueue.c:2403 | `send_mayday` |
| 47 | kernel/workqueue.c:4666 | `init_rescuer` |

Per-file totals: workqueue.c 5; kthread.c 5; bpf/cpumap.c 3; exit.c 3; ring_buffer_benchmark.c 3;
rcu/tree.c 2; trace_osnoise.c 2; the other 24 files 1 each (31 distinct files; 7×multi = 23 + 24×1 = 47).

## Excluded hits (full classification)

### Comments containing `wake_up_process(` — 11 (matched by method 1, excluded)

| file:line | Context |
|---|---|
| kernel/kthread.c:488 | kerneldoc of `kthread_create_on_cpu`: "use wake_up_process() to start" |
| kernel/kthread.c:646 | kerneldoc of `kthread_park`: "instead of calling wake_up_process():" |
| kernel/kthread.c:687 | kerneldoc of `kthread_stop`: "instead of calling wake_up_process():" |
| kernel/kthread.c:693 | kerneldoc of `kthread_stop`: "-EINTR if wake_up_process() was never called" |
| kernel/sched/core.c:981 | comment above `wake_q_add` |
| kernel/sched/core.c:999 | comment above `wake_q_add_safe` |
| kernel/sched/core.c:1026 | block comment inside `wake_up_q` |
| kernel/time/hrtimer.c:2348 | kerneldoc of `schedule_hrtimeout_range` |
| kernel/time/hrtimer.c:2382 | kerneldoc of `schedule_hrtimeout` |
| kernel/time/timer.c:2111 | kerneldoc of `schedule_timeout` |
| kernel/trace/trace_selftest.c:1236 | `/* memory barrier is in the wake_up_process() */` |

### Not a call — 1 (matched by method 1, excluded)

| file:line | Context |
|---|---|
| kernel/sched/core.c:4476 | `int wake_up_process(struct task_struct *p)` — the **definition** of the function itself (body calls `try_to_wake_up(p, TASK_NORMAL, 0)`) |

### Bare-name references without call parens — 3 (matched only by method 2, excluded)

| file:line | Classification |
|---|---|
| kernel/bpf/cpumap.c:474 | comment: "kthread_stop will wake_up_process and wait for it to complete" |
| kernel/sched/core.c:4466 | kerneldoc header: "wake_up_process - Wake up a specific process" |
| kernel/sched/core.c:4480 | `EXPORT_SYMBOL(wake_up_process);` — macro reference by name, in code but not a call |

### Judgment note: function-pointer passes

The task brief asked to document any bare `wake_up_process` passed as a callback. **There are none** in
`kernel/**/*.c` in v6.6. The closest thing is `EXPORT_SYMBOL(wake_up_process)` at kernel/sched/core.c:4480 —
a by-name macro reference, unambiguously not a "direct call", so it does not affect the total. A grader
should not penalize an answer for mentioning it as a non-call reference, but including it in the count is wrong (48 with it).

## Counting methods (two independent, agree)

1. **Method A — raw grep + manual classification**: `grep -rn "wake_up_process(" kernel/ --include='*.c'`
   → 59 lines; each line classified by reading context: 47 calls + 11 comments + 1 definition. Cross-checked
   against word-boundary grep (`\bwake_up_process\b`, 62 lines; the 3 extras all classified above).
2. **Method B — programmatic comment/string stripping**: a Python C-comment-and-string-literal stripper run
   over every `.c` file under `kernel/`, then regex `\bwake_up_process\s*\(` on the cleaned text →
   **48** in-code occurrences = 47 calls + the 1 definition (kernel/sched/core.c:4476). 48 − 1 = **47**. Agrees with Method A.

Enclosing functions determined by two independent methods that also agree on all 47:
(a) `git grep -n -p` function-context headers; (b) a column-0 brace-tracking script (kernel style puts the
function body's `{` at column 0) with matching close-brace containment check. The single disagreement
(torture.c:954, where the script's regex grabbed an inner paren of the two-line signature) was resolved by
reading kernel/torture.c:937–956: the caller is `_torture_create_kthread`. Long-function cases verified by
reading source: timerlat_irq (osnoise 1813/1819), `__irq_wake_thread` (handle.c:136), `psi_trigger_create`
(psi.c:1358), `proc_dohung_task_timeout_secs` (hung_task.c:252), `wake_dying_workers` (workqueue.c:2264).

## Question-text notes

- No problems with the question. Scope limiters are literal and load-bearing: `.h` files under kernel/ are
  out of scope (e.g. none needed here), and the huge number of `wake_up_process` calls outside `kernel/`
  (drivers/, fs/, net/, ...) must not leak in.
- "Direct call" cleanly excludes the definition (core.c:4476) and `EXPORT_SYMBOL` (core.c:4480) — the two
  most likely off-by-one/off-by-two traps. Answers of 48 or 59 indicate these classification failures.
- kernel/sched/core.c is both the *definer* and a *caller* (`wake_up_q` at core.c:1029) — a good attribution check.

## Rubric (0–3)

- **3** — Total = 47 (or 46–48 with an explicit, correct judgment note about the definition/EXPORT_SYMBOL
  lines); enclosing functions correct for the sites listed; no comment hits and no wake_up_* variants included.
- **2** — Misses ≤ 15% of sites (≥ 40 of 47 found, no spurious variant/comment inclusions), or correct site
  list with a few (≤ 5) wrong enclosing-function attributions; total consistent with the list given.
- **1** — Badly incomplete (< 40 sites) while still on-target semantically, or includes comment hits /
  the definition / EXPORT_SYMBOL in the count, or includes other wake_up_* variants, or strays outside
  kernel/ or into non-.c files.
- **0** — Wrong function, wrong scope entirely, fabricated call sites, or no enumeration at all.

GT built 2026-07-09. Methods: grep (2 patterns) + Python comment/string stripper + git grep -p + brace-tracking script + manual source reads for all ambiguous cases.
