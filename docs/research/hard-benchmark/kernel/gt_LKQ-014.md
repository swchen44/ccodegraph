# GT: LKQ-014 (references-usages, L2)

## Question (verbatim)

> "List every use of EXPORT_SYMBOL_GPL in .c files under kernel/sched/ (that subtree only). Return the exported symbol name and file:line for each, and state the exact total count. Cross-check your total with an independent counting method before answering."

Repo: Linux kernel v6.6 (`git describe` = `v6.6`, HEAD `ffc253263` "Linux 6.6") at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`

## Answer

**Exact total: 53 textual uses of `EXPORT_SYMBOL_GPL(` in `.c` files under `kernel/sched/`.**

Scope facts:
- `kernel/sched/` is flat — no subdirectories (verified with `find kernel/sched -type d`). 29 `.c` files, 9 `.h` files.
- **Zero** occurrences of `EXPORT_SYMBOL_GPL` in any `.h` file under `kernel/sched/` (verified; also zero in any non-`.c` file). The ".c files only" scope limiter is therefore not load-bearing — no scope trap in practice, but graders should know it was checked.
- **Zero** multi-line usages: `grep -rn "EXPORT_SYMBOL_GPL" --include='*.c'` minus lines containing `EXPORT_SYMBOL_GPL(` is empty — every occurrence has the open paren on the same line.
- **Zero** occurrences inside comments. (wait.c:247 has a *trailing* comment `/* For internal use only */` after a real export — it counts.)
- Distractor: there are **72** plain (non-GPL) `EXPORT_SYMBOL(` uses in the same subtree. An answer near 72 or 125 (= 53 + 72) counted the wrong macro.

## Full enumeration (53 lines, grouped by file, alphabetical)

### kernel/sched/clock.c (5)
| Symbol | file:line |
|---|---|
| sched_clock | kernel/sched/clock.c:67 |
| local_clock | kernel/sched/clock.c:319 |
| sched_clock_cpu | kernel/sched/clock.c:410 |
| sched_clock_idle_sleep_event | kernel/sched/clock.c:453 |
| sched_clock_idle_wakeup_event | kernel/sched/clock.c:472 |

### kernel/sched/core.c (18)
| Symbol | file:line |
|---|---|
| migrate_disable | kernel/sched/core.c:2425 |
| migrate_enable | kernel/sched/core.c:2460 |
| set_cpus_allowed_ptr | kernel/sched/core.c:3222 |
| kick_process | kernel/sched/core.c:3527 |
| preempt_notifier_inc | kernel/sched/core.c:4897 |
| preempt_notifier_dec | kernel/sched/core.c:4903 |
| preempt_notifier_register | kernel/sched/core.c:4916 |
| preempt_notifier_unregister | kernel/sched/core.c:4928 |
| preempt_schedule_notrace | kernel/sched/core.c:6964 |
| sched_setattr_nocheck | kernel/sched/core.c:7896 |
| sched_set_fifo | kernel/sched/core.c:7940 |
| sched_set_fifo_low | kernel/sched/core.c:7950 |
| sched_set_normal | kernel/sched/core.c:7960 |
| preempt_model_##mode (macro body — see note A) | kernel/sched/core.c:8875 |
| yield_to | kernel/sched/core.c:8988 |
| sched_show_task | kernel/sched/core.c:9185 |
| __cant_sleep | kernel/sched/core.c:10218 |
| __cant_migrate | kernel/sched/core.c:10250 |

### kernel/sched/cpufreq.c (2)
| Symbol | file:line |
|---|---|
| cpufreq_add_update_util_hook | kernel/sched/cpufreq.c:42 |
| cpufreq_remove_update_util_hook | kernel/sched/cpufreq.c:58 |

### kernel/sched/cputime.c (6)
| Symbol | file:line |
|---|---|
| task_cputime_adjusted (see note B) | kernel/sched/cputime.c:468 |
| task_cputime_adjusted (see note B) | kernel/sched/cputime.c:640 |
| vtime_guest_enter | kernel/sched/cputime.c:764 |
| vtime_guest_exit | kernel/sched/cputime.c:776 |
| kcpustat_field | kernel/sched/cputime.c:1012 |
| kcpustat_cpu_fetch | kernel/sched/cputime.c:1100 |

### kernel/sched/fair.c (1)
| Symbol | file:line |
|---|---|
| sched_smt_present | kernel/sched/fair.c:7033 |

### kernel/sched/idle.c (1)
| Symbol | file:line |
|---|---|
| play_idle_precise | kernel/sched/idle.c:372 |

### kernel/sched/isolation.c (6)
| Symbol | file:line |
|---|---|
| housekeeping_overridden | kernel/sched/isolation.c:24 |
| housekeeping_enabled | kernel/sched/isolation.c:37 |
| housekeeping_any_cpu | kernel/sched/isolation.c:54 |
| housekeeping_cpumask | kernel/sched/isolation.c:63 |
| housekeeping_affine | kernel/sched/isolation.c:71 |
| housekeeping_test_cpu | kernel/sched/isolation.c:80 |

### kernel/sched/psi.c (2)
| Symbol | file:line |
|---|---|
| psi_memstall_enter | kernel/sched/psi.c:1067 |
| psi_memstall_leave | kernel/sched/psi.c:1097 |

### kernel/sched/topology.c (2)
| Symbol | file:line |
|---|---|
| sched_numa_find_nth_cpu | kernel/sched/topology.c:2145 |
| sched_numa_hop_mask | kernel/sched/topology.c:2177 |

### kernel/sched/wait.c (7)
| Symbol | file:line |
|---|---|
| add_wait_queue_priority | kernel/sched/wait.c:48 |
| __wake_up_locked | kernel/sched/wait.c:176 |
| __wake_up_locked_key | kernel/sched/wait.c:182 |
| __wake_up_locked_key_bookmark | kernel/sched/wait.c:189 |
| __wake_up_sync_key | kernel/sched/wait.c:215 |
| __wake_up_locked_sync_key | kernel/sched/wait.c:238 |
| __wake_up_sync (trailing comment on line — still a real export) | kernel/sched/wait.c:247 |

### kernel/sched/wait_bit.c (3)
| Symbol | file:line |
|---|---|
| out_of_line_wait_on_bit_timeout | kernel/sched/wait_bit.c:79 |
| bit_wait_timeout | kernel/sched/wait_bit.c:229 |
| bit_wait_io_timeout | kernel/sched/wait_bit.c:243 |

Per-file sum: 5 + 18 + 2 + 6 + 1 + 1 + 6 + 2 + 2 + 7 + 3 = **53**.

## Notes (macro / build-system effects)

**Note A — macro-wrapped export (core.c:8875).** Line 8875 is the last line of the
`PREEMPT_MODEL_ACCESSOR(mode)` macro *definition* (under `#ifdef CONFIG_PREEMPT_DYNAMIC`):
`EXPORT_SYMBOL_GPL(preempt_model_##mode)`. It is instantiated three times at
core.c:8877-8879 (`PREEMPT_MODEL_ACCESSOR(none/voluntary/full)`), producing exports of
`preempt_model_none`, `preempt_model_voluntary`, `preempt_model_full`. Textually this is
**one** use (grep sees one line); after preprocessing it is **three** exports. An answer of
**55** (53 - 1 + 3) with this reasoning stated explicitly is a defensible alternate reading
of "every use" and should not be penalized if the macro expansion is explained.

**Note B — #ifdef duplicate.** `task_cputime_adjusted` is exported twice textually
(cputime.c:468 inside `#ifdef CONFIG_VIRT_CPU_ACCOUNTING_NATIVE`, cputime.c:640 in the
`#else` branch, ended at :649). Only one is compiled in any given build. Textual count
includes both (53); "distinct symbol names across all configs" would be 52 unexpanded /
54 with note A expansion.

**Config gating (for completeness, not for counting):** the whole file set is textual;
several exports live under config guards (e.g. preempt_model_* under CONFIG_PREEMPT_DYNAMIC,
vtime_guest_* under CONFIG_VIRT_CPU_ACCOUNTING_GEN, psi.c under CONFIG_PSI). The question
asks about source files, not a configured build, so 53 stands.

## Counting methods (must agree — they do)

**Method 1 — recursive grep with line numbers:**
```
$ grep -rn "EXPORT_SYMBOL_GPL(" kernel/sched/ --include='*.c' | wc -l
53
```
(Full line output is the enumeration above; verbatim grep output retained in GT-builder transcript.)

**Method 2 — per-file grep -c summed with awk:**
```
$ find kernel/sched -name '*.c' | sort | xargs grep -c "EXPORT_SYMBOL_GPL(" \
    | awk -F: '{s+=$2} END {print "TOTAL:", s}'
TOTAL: 53
```
Per-file breakdown: clock.c 5, core.c 18, cpufreq.c 2, cputime.c 6, fair.c 1, idle.c 1,
isolation.c 6, psi.c 2, topology.c 2, wait.c 7, wait_bit.c 3. (18 other .c files: 0.)

**Cross-checks:** `.h` files: 0 hits. Non-`.c` files: 0 hits. `EXPORT_SYMBOL_GPL` without
same-line `(`: 0 hits (no multi-line splits). Plain `EXPORT_SYMBOL(`: 72 (must NOT be counted).

## Question-text check

No discrepancy between question text and source; question is answerable as written.
Only latent ambiguity is "use" = textual occurrence (53) vs post-macro-expansion export (55);
canonical answer is **53** (grep-level, matching the question's own suggested cross-check
methodology), with Note A as the documented alternate.

## Rubric (0-3)

- **3** — Exact total **53** (or **55** with the PREEMPT_MODEL_ACCESSOR expansion explicitly
  and correctly explained) AND a complete or near-complete list (≥ 50 of 53 correct
  symbol/file:line pairs, no fabricated entries). Cross-check with a second method performed.
- **2** — Total off by 1-2 (51, 52, or 54 without correct macro reasoning), or correct total
  with minor list omissions/errors (3-6 entries missing or wrong), e.g. missed the macro line
  at core.c:8875 or one of the duplicate task_cputime_adjusted lines.
- **1** — Counted plain `EXPORT_SYMBOL` too (totals near 72 or 125), or badly incomplete list
  (fewer than ~40 correct entries), or file:line info largely absent/fabricated.
- **0** — Wrong subtree, wrong macro entirely, no enumeration, or hallucinated symbols
  dominating the list.

Grading notes: an answer stating "53" without noting the macro subtlety still earns 3 if the
list is complete — the macro line itself must appear in the list (as `preempt_model_##mode`
or as the three expanded names attributed to core.c:8875/8877-8879). The `.h` scope note is
informational only (0 hits), so no credit hinges on it.
