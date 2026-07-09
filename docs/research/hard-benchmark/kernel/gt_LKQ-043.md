# GT — LKQ-043 (data-structure, L3)

## Question (verbatim)

"List every field whose declared type is struct list_head (value fields, not pointers) directly inside the struct task_struct body (include/linux/sched.h). State explicitly how you treated fields inside conditional #ifdef blocks (count them, and say which config they need) and any inside unnamed structs/unions. Give field name + line for each and the exact total. Then show one real list_for_each_entry-family iteration over any one of these lists in kernel/ (file:line)."

## Scope

- Repo: Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`)
- File: `include/linux/sched.h`
- `struct task_struct` body: **lines 743 (`struct task_struct {`) to 1554 (`};`)**
- Counted: value fields of exact declared type `struct list_head` directly in the body.
- Excluded: pointers (`struct list_head *`), other list types (`hlist_head`, `llist_head`, `plist_node`, `robust_list_head *`), and fields of struct-typed members (nothing nested counted — question says "directly inside").
- Unnamed structs/unions: the task_struct body contains **no anonymous structs or unions** (verified; the only `union` occurrences are typed fields `union rcu_special` ×2 and `union rv_task_monitor rv[]`). So this category is empty — a correct answer must state that.
- Conditional fields: **counted in the total** and tagged with their guarding CONFIG below.

## Field table (14 total)

| # | Field | Line | Config guard |
|---|-------|------|--------------|
| 1 | `rcu_node_entry` | 847 | `CONFIG_PREEMPT_RCU` |
| 2 | `rcu_tasks_holdout_list` | 856 | `CONFIG_TASKS_RCU` |
| 3 | `trc_holdout_list` | 863 | `CONFIG_TASKS_TRACE_RCU` |
| 4 | `trc_blkd_node` | 864 | `CONFIG_TASKS_TRACE_RCU` |
| 5 | `tasks` | 870 | unconditional |
| 6 | `children` | 989 | unconditional |
| 7 | `sibling` | 990 | unconditional |
| 8 | `ptraced` | 999 | unconditional |
| 9 | `ptrace_entry` | 1000 | unconditional |
| 10 | `thread_group` | 1005 | unconditional |
| 11 | `thread_node` | 1006 | unconditional |
| 12 | `cg_list` | 1227 | `CONFIG_CGROUPS` |
| 13 | `pi_state_list` | 1238 | `CONFIG_FUTEX` (outside the nested `CONFIG_COMPAT` block, which ends at line 1237) |
| 14 | `perf_event_list` | 1246 | `CONFIG_PERF_EVENTS` |

## Totals

- **Unconditional: 7** (tasks, children, sibling, ptraced, ptrace_entry, thread_group, thread_node)
- **Conditional (#ifdef-gated): 7** (rcu_node_entry, rcu_tasks_holdout_list, trc_holdout_list, trc_blkd_node, cg_list, pi_state_list, perf_event_list)
- **Grand total: 14**

## Excluded (not `struct list_head` value fields)

There are **zero** fields of type `struct list_head *` directly in the body. Near-misses an answer might wrongly include:

| Field | Line | Why excluded | Guard |
|-------|------|--------------|-------|
| `preempt_notifiers` | 826 | `struct hlist_head` (different type) | `CONFIG_PREEMPT_NOTIFIERS` |
| `robust_list` | 1234 | `struct robust_list_head __user *` (different type AND pointer) | `CONFIG_FUTEX` |
| `compat_robust_list` | 1236 | `struct compat_robust_list_head __user *` (different type AND pointer) | `CONFIG_FUTEX` + `CONFIG_COMPAT` |
| `kretprobe_instances` | 1509 | `struct llist_head` (different type) | `CONFIG_KRETPROBES` |
| `rethooks` | 1512 | `struct llist_head` (different type) | `CONFIG_RETHOOK` |

Also plausible confusions: `pushable_tasks` (line 872, `struct plist_node`, CONFIG_SMP) and `pid_links` (line 1004, `struct hlist_node[]`).

## Iterator example (kernel/)

`kernel/exit.c:1499` in `do_wait_thread()`:

```c
list_for_each_entry(p, &tsk->children, sibling) {
```

Iterates the **`children`** list (line 989 of task_struct), using each child's **`sibling`** member (line 990) as the link. Other acceptable examples:

- `kernel/exit.c:1513` — `list_for_each_entry(p, &tsk->ptraced, ptrace_entry)` (ptraced/ptrace_entry)
- `kernel/exit.c:471`, `kernel/exit.c:479`, `kernel/exit.c:702` — over `children` via `sibling`
- `kernel/exit.c:603`, `kernel/exit.c:763` — `list_for_each_entry_safe(..., ptrace_entry)`
- `kernel/fork.c:3223` — `list_for_each_entry(child, &parent->children, sibling)`

Any real `list_for_each_entry`-family call in `kernel/` whose head is one of the 14 fields (or whose member arg is one of them, e.g. `sibling`, `ptrace_entry`, `thread_node`, `cg_list`) is acceptable with correct file:line.

## Verification (two methods, agreeing)

1. **grep sweep**: all lines containing `list_head` in lines 743–1554 enumerated by awk; hand-classified into value fields vs other types/pointers → 14 value fields.
2. **Python #ifdef walker**: script walked lines 743–1554 tracking a `#if/#ifdef/#else/#endif` stack, matched `^struct\s+list_head\s+\*?name;`, emitted each field with its live guard stack → identical 14 fields, identical guards, 7 unconditional / 7 conditional. Guard contexts additionally spot-checked by direct reads of lines 840–875, 984–1009, 1222–1249.

## Question-text notes

- The question presupposes there may be list_head fields inside unnamed structs/unions and `struct list_head *` pointers; **both sets are empty** in v6.6. A good answer states this explicitly rather than inventing entries. Not a GT defect — the question asks how they were treated, and "none exist" is the correct treatment.
- No ambiguity in struct boundaries: exactly one `struct task_struct {` definition in the file.

## Rubric (0–3)

- **3** — Grand total correct within ±1 (i.e., 13–15 with the list substantially matching the 14 above) AND conditional fields are tagged with their specific CONFIG guards (at least the 7 conditional fields identified as conditional with mostly-correct configs); includes a valid kernel/ iterator with correct file:line.
- **2** — Field list mostly right (roughly 11+ of 14 found) but no/incorrect config tagging, OR total off by 2–3; iterator example present but possibly imprecise (wrong line, right file/field).
- **1** — Badly incomplete: only the famous unconditional fields (children/sibling/tasks...) found with conditional ones largely missed, or major type confusion (counts hlist_head/llist_head/pointers), or no usable iterator example.
- **0** — Wrong struct/file, fabricated fields/lines, or no meaningful enumeration.
