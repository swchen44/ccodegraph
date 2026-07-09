# GT — LKQ-077 (locking-rcu, L3)

**Repo:** Linux kernel v6.6 (`repos/linux-v6.6`)
**Verified:** 2026-07-09, by grep + source read of every callback definition body.

## Question (verbatim)

> "Find two distinct call_rcu() call sites, one under kernel/sched/ and one under kernel/rcu/ or kernel/ (top level). For each: file:line, the callback function passed, and the callback's definition file:line. For one of them, state what resource the callback releases."

## Scope check (no question-text problem)

- `kernel/sched/`: **7** literal `call_rcu(` call sites — scope valid.
- `kernel/` top level (`kernel/*.c`): **22** call sites — scope valid.
- `kernel/rcu/`: **3** genuine invocation sites (test/benchmark code) — scope valid, though thin; graders should expect most answers to pick a `kernel/*.c` site.
- No flag needed. Question text is answerable as written.

## Scope 1 — ALL valid sites under kernel/sched/ (7)

| # | Call site (file:line) | Callback passed | Callback definition (file:line, verified) |
|---|---|---|---|
| 1 | kernel/sched/topology.c:456 | `destroy_perf_domain_rcu` | kernel/sched/topology.c:325 |
| 2 | kernel/sched/topology.c:465 | `destroy_perf_domain_rcu` | kernel/sched/topology.c:325 |
| 3 | kernel/sched/topology.c:521 | `free_rootdomain` | kernel/sched/topology.c:473 |
| 4 | kernel/sched/topology.c:534 | `free_rootdomain` | kernel/sched/topology.c:473 |
| 5 | kernel/sched/topology.c:654 | `destroy_sched_domains_rcu` | kernel/sched/topology.c:640 |
| 6 | kernel/sched/core.c:10380 | `sched_free_group_rcu` | kernel/sched/core.c:10367 |
| 7 | kernel/sched/core.c:10435 | `sched_unregister_group_rcu` | kernel/sched/core.c:10426 |

Notes:
- Sites 1-2 are in `build_perf_domains()`; enclosing region is under `#if defined(CONFIG_ENERGY_MODEL) && defined(CONFIG_CPU_FREQ_GOV_SCHEDUTIL)`.
- Site 3 is in `rq_attach_root()`, site 4 in `sched_put_rd()`.
- Site 5 is in `destroy_sched_domains()`.
- Sites 6-7 are in `sched_unregister_group()` and `sched_destroy_group()` respectively.

## Scope 2a — ALL valid sites in kernel/*.c top level (22)

| # | Call site (file:line) | Callback passed | Callback definition (file:line, verified) |
|---|---|---|---|
| 1 | kernel/audit.c:517 | `auditd_conn_free` | kernel/audit.c:475 |
| 2 | kernel/audit.c:657 | `auditd_conn_free` | kernel/audit.c:475 |
| 3 | kernel/audit_tree.c:158 | `__put_chunk` | kernel/audit_tree.c:145 |
| 4 | kernel/audit_tree.c:559 | `audit_free_rule_rcu` | kernel/auditfilter.c:99 (cross-file; decl kernel/audit.h:250) |
| 5 | kernel/audit_watch.c:306 | `audit_free_rule_rcu` | kernel/auditfilter.c:99 |
| 6 | kernel/audit_watch.c:338 | `audit_free_rule_rcu` | kernel/auditfilter.c:99 |
| 7 | kernel/auditfilter.c:1067 | `audit_free_rule_rcu` | kernel/auditfilter.c:99 |
| 8 | kernel/auditfilter.c:1428 | `audit_free_rule_rcu` | kernel/auditfilter.c:99 |
| 9 | kernel/cred.c:156 | `put_cred_rcu` | kernel/cred.c:97 |
| 10 | kernel/exit.c:232 | `delayed_put_task_struct` | kernel/exit.c:218 |
| 11 | kernel/fork.c:230 | `thread_stack_free_rcu` | kernel/fork.c:215 (CONFIG_VMAP_STACK branch) |
| 12 | kernel/fork.c:353 | `thread_stack_free_rcu` | kernel/fork.c:344 (!VMAP_STACK, THREAD_SIZE >= PAGE_SIZE branch) |
| 13 | kernel/fork.c:388 | `thread_stack_free_rcu` | kernel/fork.c:379 (kmem_cache branch, THREAD_SIZE < PAGE_SIZE) |
| 14 | kernel/fork.c:546 | `vm_area_free_rcu_cb` | kernel/fork.c:532 |
| 15 | kernel/fork.c:2196 | `__delayed_free_task` | kernel/fork.c:2186 |
| 16 | kernel/kprobes.c:1897 | `free_rp_inst_rcu` | kernel/kprobes.c:1880 |
| 17 | kernel/pid.c:159 | `delayed_put_pid` | kernel/pid.c:123 |
| 18 | kernel/pid_namespace.c:142 | `delayed_free_pidns` | kernel/pid_namespace.c:127 |
| 19 | kernel/tracepoint.c:133 | `rcu_free_old_probes` | kernel/tracepoint.c:119 |
| 20 | kernel/tracepoint.c:164 | `rcu_free_old_probes` | kernel/tracepoint.c:119 |
| 21 | kernel/watch_queue.c:428 | `free_watch` | kernel/watch_queue.c:414 |
| 22 | kernel/workqueue.c:4027 | `rcu_free_pool` | kernel/workqueue.c:3938 |
| 23 | kernel/workqueue.c:4130 | `rcu_free_pwq` | kernel/workqueue.c:4095 |
| 24 | kernel/workqueue.c:4138 | `rcu_free_wq` | kernel/workqueue.c:3927 |

(24 rows because fork.c's three `thread_stack_free_rcu` sites pair with three config-dependent definitions; any consistent site+definition pairing from the same `#if` branch is correct. Rows 11-13 pairings verified against the `#if`/`#else` structure at kernel/fork.c:182,188,375,414.)

- NOT a call site: kernel/sys.c:973 (comment only).

## Scope 2b — ALL valid sites under kernel/rcu/ (3)

| # | Call site (file:line) | Callback passed | Callback definition (file:line, verified) |
|---|---|---|---|
| 1 | kernel/rcu/rcuscale.c:661 | `kfree_call_rcu` | kernel/rcu/rcuscale.c:616 |
| 2 | kernel/rcu/rcuscale.c:774 | `call_rcu_lazy_test1` | kernel/rcu/rcuscale.c:740 |
| 3 | kernel/rcu/update.c:607 | `test_callback` | kernel/rcu/update.c:585 |

NOT call sites (common traps — do not accept):
- kernel/rcu/tiny.c:170 and kernel/rcu/tree.c:2765 — these are the **definitions** of `call_rcu()` itself.
- kernel/rcu/tiny.c:254 — calls `__kvfree_call_rcu()`, a different function.
- kernel/rcu/rcuscale.c:211 — definition of `srcu_call_rcu()` wrapper, not an invocation of `call_rcu()`.
- All other grep hits in kernel/rcu/ are comments/strings.

## Callback definition bodies (verified excerpts)

**`free_rootdomain`** — kernel/sched/topology.c:473:
```c
static void free_rootdomain(struct rcu_head *rcu)
{
	struct root_domain *rd = container_of(rcu, struct root_domain, rcu);

	cpupri_cleanup(&rd->cpupri);
	cpudl_cleanup(&rd->cpudl);
	free_cpumask_var(rd->dlo_mask);
	free_cpumask_var(rd->rto_mask);
	free_cpumask_var(rd->online);
	free_cpumask_var(rd->span);
	free_pd(rd->pd);
	kfree(rd);
}
```

**`destroy_perf_domain_rcu`** (topology.c:325): `container_of(rp, struct perf_domain, rcu)` then `free_pd(pd)`.
**`destroy_sched_domains_rcu`** (topology.c:640): walks `sd->parent` chain calling `destroy_sched_domain()` on each.
**`sched_free_group_rcu`** (core.c:10367): calls `sched_free_group()` -> frees fair/rt sched groups, autogroup, `kmem_cache_free(task_group_cache, tg)`.
**`sched_unregister_group_rcu`** (core.c:10426): calls `sched_unregister_group()`, which itself chains a second `call_rcu(&tg->rcu, sched_free_group_rcu)` (core.c:10380).
**`delayed_put_task_struct`** (exit.c:218): flushes kprobe/rethook/perf state then `put_task_struct(tsk)` (drops final task_struct ref).
**`audit_free_rule_rcu`** (auditfilter.c:99): `container_of(head, struct audit_entry, rcu)` then `audit_free_rule(e)`.
**`put_cred_rcu`** (cred.c:97): puts keyrings/group_info/uid/ucounts/user_ns, then `kmem_cache_free(cred_jar, cred)`.
**`__put_chunk`** (audit_tree.c:145): `audit_put_chunk(chunk)`.
**`kfree_call_rcu`** (rcuscale.c:616): `kfree(container_of(rh, struct kfree_obj, rh))`.
**`test_callback`** (update.c:585): increments `rcu_self_test_counter` and prints — releases nothing (self-test).
**`call_rcu_lazy_test1`** (rcuscale.c:740): records jiffies + sets flag — releases nothing (laziness test).

## Resource-release explanation (canonical example)

**Site kernel/sched/topology.c:521** (in `rq_attach_root()`, also topology.c:534 in `sched_put_rd()`): `call_rcu(&old_rd->rcu, free_rootdomain)`.

`free_rootdomain()` (topology.c:473-484) releases the **`struct root_domain` and all its embedded resources** after the RCU grace period, once no CPU can still hold an RCU-protected reference to the old root domain:
- `cpupri_cleanup(&rd->cpupri)` / `cpudl_cleanup(&rd->cpudl)` — free the per-CPU priority / deadline management structures;
- four `free_cpumask_var()` calls — free the `dlo_mask`, `rto_mask`, `online`, `span` cpumasks;
- `free_pd(rd->pd)` — free the attached perf-domain list;
- `kfree(rd)` — free the `root_domain` object itself.

(If the answer picks a different site, accept any correct release statement, e.g. `delayed_put_task_struct` drops the final `task_struct` reference via `put_task_struct()`; `put_cred_rcu` frees the credential back to `cred_jar` after putting its keyrings/uid/namespaces; `thread_stack_free_rcu` frees the kernel thread stack via `vfree`/`__free_pages`/`kmem_cache_free` depending on config.)

## Rubric (0-3)

- **3** — Two distinct sites, one from each required scope (any row of the Scope-1 table + any row of Scope-2a or Scope-2b), each with correct file:line (±2 lines tolerance), correct callback name, correct definition file:line (±2 lines; fork.c: any definition from a consistent config branch accepted), AND a correct resource-release statement for at least one site consistent with the verified body (test-only callbacks `test_callback`/`call_rcu_lazy_test1` may be truthfully described as "releases nothing — test instrumentation", which counts if the OTHER site's release is not required; if the release claim is made about such a callback and asserts it frees something, deduct).
- **2** — Both sites and callbacks correct, but one definition location missing/wrong, or the release explanation vague (e.g. "frees memory" with no specific resource) or attached to the wrong callback.
- **1** — Only one scope satisfied correctly (e.g. both sites from kernel/sched/, or one site correct and the other invalid — e.g. cites tiny.c:170/tree.c:2765 definition lines as "call sites").
- **0** — No valid site in either scope, or callback names fabricated.

Grader traps: citing kernel/rcu/tiny.c:170 or tree.c:2765 (definitions of call_rcu, not call sites); kernel/sys.c:973 (comment); kvfree_call_rcu / srcu_call_rcu confusion; claiming `sched_unregister_group_rcu` directly frees the task_group (it unregisters, then chains a second call_rcu that frees).
