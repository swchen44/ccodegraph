# GT — LKQ-027 (entry-path, L3)

## Question (verbatim)

"Trace the paths from the fork and clone syscall definitions (kernel/fork.c) to copy_process(): name each named function hop in order with file:line for both syscalls, and state which shared intermediate helper both paths funnel through."

Repo: Linux kernel v6.6 (verified `git describe` = v6.6). All paths relative to repo root; all line numbers verified by direct read.

## Answer

Both syscall entry points are defined in `kernel/fork.c` and both make exactly **one named-function hop** — a direct call to `kernel_clone()` — which in turn calls `copy_process()`. The shared intermediate helper both paths funnel through is **`kernel_clone()`**.

### Chain 1: fork

1. `SYSCALL_DEFINE0(fork)` — definition at `kernel/fork.c:2991`
   - builds `struct kernel_clone_args args = { .exit_signal = SIGCHLD };` at `kernel/fork.c:2994-2996`
   - calls `kernel_clone(&args)` at `kernel/fork.c:2998`
2. `kernel_clone()` — definition at `kernel/fork.c:2868`
   - calls `copy_process(NULL, trace, NUMA_NO_NODE, args)` at `kernel/fork.c:2909`
3. `copy_process()` — definition at `kernel/fork.c:2240`

Hop chain: `sys_fork` (fork.c:2991) → `kernel_clone` (call fork.c:2998, def fork.c:2868) → `copy_process` (call fork.c:2909, def fork.c:2240).

### Chain 2: clone

1. `SYSCALL_DEFINE5(clone, ...)` — definition at `kernel/fork.c:3020` / `3025` / `3036`, or `SYSCALL_DEFINE6(clone, ...)` at `kernel/fork.c:3030`, depending on arch config (see guard notes; shared body opens at `kernel/fork.c:3041`)
   - builds `struct kernel_clone_args args = { .flags, .pidfd, .child_tid, .parent_tid, .exit_signal, .stack, .tls };` at `kernel/fork.c:3042-3050`
   - calls `kernel_clone(&args)` at `kernel/fork.c:3052`
2. `kernel_clone()` — definition at `kernel/fork.c:2868`
   - calls `copy_process(NULL, trace, NUMA_NO_NODE, args)` at `kernel/fork.c:2909`
3. `copy_process()` — definition at `kernel/fork.c:2240`

Hop chain: `sys_clone` (fork.c:3020/3025/3030/3036) → `kernel_clone` (call fork.c:3052, def fork.c:2868) → `copy_process` (call fork.c:2909, def fork.c:2240).

### Shared intermediate helper

**`kernel_clone()`** (`kernel/fork.c:2868`). It is the single funnel: it performs the CLONE_PIDFD/CLONE_PARENT_SETTID sanity check, ptrace-event selection, then calls `copy_process()` at `kernel/fork.c:2909` and handles post-copy wakeup/vfork completion.

## kargs (struct kernel_clone_args) construction

- **fork** (`kernel/fork.c:2994-2996`): only `.exit_signal = SIGCHLD` — everything else zero (no shared VM, no flags).
- **clone** (`kernel/fork.c:3042-3050`):
  - `.flags = (lower_32_bits(clone_flags) & ~CSIGNAL)` (line 3043)
  - `.pidfd = parent_tidptr` (line 3044 — legacy clone reuses `parent_tidptr` as the pidfd return slot for CLONE_PIDFD; this is why kernel_clone rejects CLONE_PIDFD + CLONE_PARENT_SETTID with the same pointer at fork.c:2886-2889)
  - `.child_tid = child_tidptr` (3045), `.parent_tid = parent_tidptr` (3046)
  - `.exit_signal = (lower_32_bits(clone_flags) & CSIGNAL)` (3047)
  - `.stack = newsp` (3048), `.tls = tls` (3049)

## Conditional-compilation guard notes (precision credit; not required for full score)

- `SYSCALL_DEFINE0(fork)` is guarded by `#ifdef __ARCH_WANT_SYS_FORK` (fork.c:2990, closed at 3004). Inside the body, `#ifdef CONFIG_MMU` (fork.c:2993): the kargs build + `kernel_clone()` call exist only under CONFIG_MMU; the `#else` branch (fork.c:2999-3002) returns `-EINVAL` ("can not support in nommu mode") — on nommu, the fork path to copy_process does not exist.
- The clone definition is guarded by `#ifdef __ARCH_WANT_SYS_CLONE` (fork.c:3018, closed at 3054), with four argument-order variants selected by arch config:
  - `CONFIG_CLONE_BACKWARDS` → `SYSCALL_DEFINE5` at fork.c:3020 (tls before child_tidptr)
  - `CONFIG_CLONE_BACKWARDS2` → `SYSCALL_DEFINE5` at fork.c:3025 (newsp before clone_flags)
  - `CONFIG_CLONE_BACKWARDS3` → `SYSCALL_DEFINE6` at fork.c:3030 (extra stack_size arg)
  - default → `SYSCALL_DEFINE5` at fork.c:3036
  All four share the same body (fork.c:3041-3053) and the same `kernel_clone(&args)` call at fork.c:3052.
- Adjacent but out of scope (question names only fork and clone): `SYSCALL_DEFINE0(vfork)` at fork.c:3007 under `__ARCH_WANT_SYS_VFORK`, and `SYSCALL_DEFINE2(clone3, ...)` at fork.c:3194 under `__ARCH_WANT_SYS_CLONE3` (calls `kernel_clone(&kargs)` at fork.c:3210). An answer that includes these as extras is fine; substituting them for fork/clone is not.

## Question-text check

No defects. Both syscall definitions are in `kernel/fork.c` as stated, and a single shared intermediate helper genuinely exists (`kernel_clone`). Note the question says "each named function hop" — there is exactly one intermediate hop per chain (`kernel_clone`); answers inventing extra hops (e.g. `_do_fork`, which was renamed to `kernel_clone` in v5.10) are wrong for v6.6.

## Rubric (0-3)

- **3** — Both chains complete and correct with file:line evidence at each hop (fork def ~2991 → kernel_clone call ~2998; clone def ~3020/3025/3030/3036 → kernel_clone call ~3052; kernel_clone def ~2868 → copy_process call ~2909; copy_process def ~2240), AND explicitly names `kernel_clone` as the shared funnel. Small line drift (±5) acceptable; guard/#ifdef notes and kargs details not required but award precision.
- **2** — Both chains traced with kernel_clone named as the funnel, but missing or wrong on some file:line evidence (e.g. cites only one of the def/call-site pairs, or misses that clone has config-dependent definition variants while citing a wrong line for the variant claimed).
- **1** — Only one chain traced correctly, or the funnel misidentified/unnamed (e.g. says both "call copy_process" directly, or names the stale `_do_fork`), or chains asserted without line evidence.
- **0** — Wrong functions, wrong file, hallucinated hops, or no verifiable trace.

Scoring must NOT require the `__ARCH_WANT_SYS_FORK` / `__ARCH_WANT_SYS_CLONE` / `CONFIG_MMU` guard notes or the CLONE_BACKWARDS variant enumeration, but their correct presence distinguishes a precise 3 and may compensate for minor line drift.
