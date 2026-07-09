# GT — LKQ-053 (kconfig-build, L3)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`, tag `v6.6`, Makefile VERSION=6 PATCHLEVEL=6 SUBLEVEL=0)

## Question (verbatim)

> Locate where preempt_schedule() (kernel/sched/core.c) is conditionally compiled: quote the exact preprocessor guard around its definition (file:line), name the CONFIG symbol used, and find where that symbol is declared in Kconfig (file:line). If the guard symbol differs from CONFIG_PREEMPT itself (e.g. CONFIG_PREEMPTION), explain the relationship between the two per the Kconfig declarations.

## Ground truth

### Preprocessor guard

`kernel/sched/core.c:6875` — the guard is:

```c
#ifdef CONFIG_PREEMPTION
```

The guarded block closes at `kernel/sched/core.c:6987`:

```c
#endif /* CONFIG_PREEMPTION */
```

The `preempt_schedule()` definition itself is inside that block:

```c
6880	asmlinkage __visible void __sched notrace preempt_schedule(void)
6881	{
6882		/*
6883		 * If there is a non-zero preempt_count or interrupts are disabled,
6884		 * we do not want to preempt the current task. Just return..
6885		 */
6886		if (likely(!preemptible()))
6887			return;
6888		preempt_schedule_common();
6889	}
6890	NOKPROBE_SYMBOL(preempt_schedule);
6891	EXPORT_SYMBOL(preempt_schedule);
```

**CONFIG symbol used by the guard: `CONFIG_PREEMPTION`** (NOT `CONFIG_PREEMPT`). Grep confirms no `#ifdef CONFIG_PREEMPT` guard anywhere around this definition; the only enclosing conditional between line 6875 and the definition is `#ifdef CONFIG_PREEMPTION`.

### Kconfig declaration of the guard symbol

`kernel/Kconfig.preempt:92–94` — `PREEMPTION` is a promptless (non-user-selectable) bool:

```
92	config PREEMPTION
93	       bool
94	       select PREEMPT_COUNT
```

(Note: lines 93–94 in the source use space indentation, not tabs — quoted verbatim above.)

### Kconfig declaration of CONFIG_PREEMPT

`kernel/Kconfig.preempt:51–54` (inside the `choice "Preemption Model"` block, lines 14–87):

```
51	config PREEMPT
52		bool "Preemptible Kernel (Low-Latency Desktop)"
53		depends on !ARCH_NO_PREEMPT
54		select PREEMPT_BUILD
```

### Relationship per the Kconfig declarations (v6.6 — this is the trap)

In v6.6 the relationship is **indirect** for PREEMPT and **direct** for PREEMPT_RT:

- `config PREEMPT` (kernel/Kconfig.preempt:51) does **NOT** directly `select PREEMPTION`. It has `select PREEMPT_BUILD` (line 54).
- `config PREEMPT_BUILD` (kernel/Kconfig.preempt:9–12) is the intermediate promptless symbol that does the select:

  ```
  9	config PREEMPT_BUILD
  10		bool
  11		select PREEMPTION
  12		select UNINLINE_SPIN_UNLOCK if !ARCH_INLINE_SPIN_UNLOCK
  ```

  So the chain is **PREEMPT → selects PREEMPT_BUILD → selects PREEMPTION**.
- `config PREEMPT_RT` (kernel/Kconfig.preempt:70–73) selects PREEMPTION **directly**: `select PREEMPTION` at line 73.
- `config PREEMPT_DYNAMIC` (kernel/Kconfig.preempt:96–100) also reaches PREEMPTION via `select PREEMPT_BUILD` (line 100).
- PREEMPTION itself is never user-visible (no prompt); it exists so code like `preempt_schedule()` can be compiled in for *any* preemptible model (full PREEMPT, PREEMPT_RT, or PREEMPT_DYNAMIC builds) without testing each model symbol. It in turn `select`s PREEMPT_COUNT (line 94).

Exhaustive check: the **only** two `select PREEMPTION` sites in the entire v6.6 tree are `kernel/Kconfig.preempt:11` (under PREEMPT_BUILD) and `kernel/Kconfig.preempt:73` (under PREEMPT_RT). There is no `select PREEMPTION` under `config PREEMPT` — an answer asserting "PREEMPT selects PREEMPTION" as a *direct* select statement is reciting pre-v5.16 Kconfig (before commit c597bfddc9e9, "sched: Provide Kconfig support for default dynamic preempt mode", which introduced PREEMPT_BUILD).

### Bonus context (adjacent companion definitions, all inside the same CONFIG_PREEMPTION block)

- `NOKPROBE_SYMBOL(preempt_schedule);` — kernel/sched/core.c:6890; `EXPORT_SYMBOL(preempt_schedule);` — kernel/sched/core.c:6891.
- CONFIG_PREEMPT_DYNAMIC static-call/static-key machinery for preempt_schedule — kernel/sched/core.c:6893–6912, including `DEFINE_STATIC_CALL(preempt_schedule, preempt_schedule_dynamic_enabled);` (line 6899) and `EXPORT_STATIC_CALL_TRAMP(preempt_schedule);` (line 6900), plus `dynamic_preempt_schedule()` (lines 6903–6910) for the HAVE_PREEMPT_DYNAMIC_KEY variant.
- `preempt_schedule_notrace()` — kernel/sched/core.c:6928 (asmlinkage entry used by tracing), with its own dynamic machinery at 6966–6985.
- `preempt_schedule_irq()` — kernel/sched/core.c:6995 — is **outside** the guard (after the `#endif` at 6987); it is compiled unconditionally. An answer placing preempt_schedule_irq inside the CONFIG_PREEMPTION block is wrong on that detail (does not affect core scoring).

### Verification notes

- Guard verified by listing all preprocessor directives in kernel/sched/core.c between lines 6800–7010: the block structure is `#ifdef CONFIG_PREEMPTION` (6875) … `#endif /* CONFIG_PREEMPTION */` (6987), with nested `#ifdef CONFIG_PREEMPT_DYNAMIC` sub-blocks (6893–6912, 6966–6985) that do not guard preempt_schedule() itself.
- Only one definition of `preempt_schedule` exists in kernel/sched/core.c (line 6880).
- Question-text problems: none — the question itself anticipates the guard differing from CONFIG_PREEMPT and asks for the relationship "per the Kconfig declarations", which is answerable exactly. **Flag for graders:** the commonly memorized claim "config PREEMPT selects PREEMPTION" is stale for v6.6 — the direct selector is PREEMPT_BUILD (PREEMPT_RT is the only model selecting PREEMPTION directly). GT construction guidance that expected a direct "PREEMPT selects PREEMPTION" line reflects pre-v5.16 sources; grade against the v6.6 text above.

## Rubric (0–3)

Prerequisite for scoring above 0: identifies the guard symbol as `CONFIG_PREEMPTION`. **An answer claiming the guard is `CONFIG_PREEMPT` scores at most 1** (and only if the Kconfig sites cited are otherwise real).

- **3** — Guard quoted as `#ifdef CONFIG_PREEMPTION` at kernel/sched/core.c:6875 (accept ±3 lines; accept also citing the definition at 6880 and/or the `#endif` at 6987); `config PREEMPTION` located at kernel/Kconfig.preempt:92 (±3); `config PREEMPT` located at kernel/Kconfig.preempt:51 (±3); AND the relationship stated correctly per v6.6 text: PREEMPT reaches PREEMPTION indirectly via `select PREEMPT_BUILD` → `select PREEMPTION` (accept an answer that says "PREEMPT selects PREEMPTION" only if it shows the PREEMPT_BUILD chain or quotes lines 11/54; mentioning PREEMPT_RT's direct `select PREEMPTION` at line 73 strengthens but the PREEMPT chain is the required part).
- **2** — Correct guard symbol (CONFIG_PREEMPTION) and correct core.c guard site, and PREEMPTION's Kconfig site found, but the relationship is stated as a *direct* "PREEMPT selects PREEMPTION" without the PREEMPT_BUILD intermediary (stale-knowledge answer), or one Kconfig file:line is missing/wrong (>±3).
- **1** — Correct guard symbol but no valid Kconfig site (or fabricated lines); OR guard claimed to be CONFIG_PREEMPT while the Kconfig discussion is otherwise grounded in the real file.
- **0** — Wrong guard symbol with fabricated or absent evidence; guard site not in kernel/sched/core.c; or relationship invented (e.g. "PREEMPTION selects PREEMPT", "PREEMPTION depends on PREEMPT").
