# GT — LKQ-001 (symbol-definition, L1)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`)
**GT built:** 2026-07-09. Verified with TWO independent methods (grep -n; Universal Ctags 6.2.1 `ctags -x --c-kinds=f`). Question text checked against source: **no factual errors in the question** (it names no file, so nothing to contradict).

## Question (verbatim)

> "Find the definition of copy_process() (the function body, not any declaration or comment mention). Return the file path, the line number where the definition starts, and the full signature including return type, storage class/attributes, and all parameters. State explicitly whether the function is static."

## Definitive answer

- **File:** `kernel/fork.c`
- **Line where the definition starts:** **2240**
  - Line-number convention note: in v6.6 the attribute (`__latent_entropy`), the return type (`struct task_struct *`), and the function name `copy_process(` are ALL on the same line, **2240**. So the "attribute/return-type line" convention and the "function-name line" convention **coincide at 2240** — there is no ambiguity to arbitrate.
  - Parameters continue on lines 2241–2244; opening brace `{` is line **2245**; body's closing `}` is line **2799**.
  - The doc comment above the function spans 2232–2239. Answering 2232 (comment start) is **wrong** — the question explicitly excludes comment mentions.
- **Full signature (verbatim, lines 2240–2244):**

```c
__latent_entropy struct task_struct *copy_process(
					struct pid *pid,
					int trace,
					int node,
					struct kernel_clone_args *args)
```

- **Static?** **No.** There is no `static` keyword; the function has **external linkage** and is declared in a public header:
  - Declaration (NOT the definition): `include/linux/sched/task.h:95-96`:
    ```c
    struct task_struct *copy_process(struct pid *pid, int trace, int node,
    				 struct kernel_clone_args *args);
    ```
  - External callers exist outside fork.c: `kernel/vhost_task.c:130` (`tsk = copy_process(NULL, 0, NUMA_NO_NODE, &args);`) — impossible if it were static.
- **Attribute:** `__latent_entropy` is present and part of the correct signature. Build-system note: it expands to `__attribute__((latent_entropy))` only when the GCC latent_entropy plugin is active (`include/linux/compiler-gcc.h:44-46`, gated on `LATENT_ENTROPY_PLUGIN && !__CHECKER__`); otherwise it expands to nothing (`include/linux/compiler_types.h:316-318`). Either way, the token appears verbatim in the source signature, so a full-signature answer must include it.
- **Return type:** `struct task_struct *`. Parameters: `struct pid *pid`, `int trace`, `int node`, `struct kernel_clone_args *args`.

## Evidence (two independent methods)

1. `grep -n "copy_process" kernel/fork.c` → `2240:__latent_entropy struct task_struct *copy_process(` (the only definition-shaped hit; all others are calls or comments).
2. `ctags -x --c-kinds=f kernel/fork.c | grep -w copy_process` → `copy_process  function  2240  kernel/fork.c  __latent_entropy struct task_struct *copy_process(`.

## Disambiguation notes

Tree-wide search (`*.c`, `*.h`, plus unscoped sweep of `tools/`, `scripts/`, `arch/`, `Documentation/`):

- There is **exactly one function named `copy_process` in the entire tree** — the kernel/fork.c definition above. Nothing in `tools/`, `scripts/`, or any `arch/`.
- `include/linux/sched/task.h:95` is a **declaration**, not the definition (no body). An answer citing it scores as wrong-location.
- Similarly named but DIFFERENT symbols an agent might confuse (none is a valid answer):
  - `rcu_copy_process` — `static inline`, kernel/fork.c:1967
  - `klp_copy_process` — kernel/livepatch/transition.c (+ decl in include/linux/livepatch.h)
  - `uprobe_copy_process` — kernel/events/uprobes.c (+ decl in include/linux/uprobes.h)
- Comment-only mentions (not answers): arch/x86/entry/entry_32.S:10, arch/arm64/kernel/process.c:301, include/linux/pid.h:163, Documentation/trace/ftrace.rst:3603.
- Call sites in fork.c itself (not the definition): 2828, 2857, 2909.

## Scoring rubric (0–3)

- **3** — File `kernel/fork.c` AND start line 2240 (accept 2238–2242, i.e. ±2, to tolerate any attribute-line/name-line convention; 2245 acceptable ONLY if explicitly stated as the opening-brace line alongside the signature) AND full signature including `__latent_entropy`, return type `struct task_struct *`, and all four parameters (`struct pid *pid, int trace, int node, struct kernel_clone_args *args`) AND explicitly states the function is **not static** (external linkage).
- **2** — Correct file + correct line (within tolerance) + correct not-static verdict, but signature incomplete in exactly one minor way (e.g., omits `__latent_entropy`, or paraphrases parameter names while types are correct).
- **1** — Correct file and function identified with roughly correct signature, but line number wrong beyond tolerance (e.g., cites 2232 comment start, or a call site), OR omits/fudges the static verdict, OR two or more signature omissions.
- **0** — Wrong file (e.g., cites `include/linux/sched/task.h` declaration as the definition), wrong function (e.g., `rcu_copy_process`), claims the function is static, or fabricated signature/line.

Auto-fail notes for graders: "static" verdict must be explicit per the question; an answer that never addresses staticness caps at 1.
