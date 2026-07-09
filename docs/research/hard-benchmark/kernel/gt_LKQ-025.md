# GT: LKQ-025 (entry-path, L3)

**Repo**: Linux kernel v6.6 (`repos/linux-v6.6`, tag `v6.6`). All file:line references verified against this tree.

## Question (verbatim)

> "Trace the x86_64 read() system call path from the syscall definition to the VFS helper: start at the SYSCALL_DEFINE3(read, ...) site (file:line) and name every named function hop in order, with file:line for each, ending at vfs_read(). Also state, from in-tree (non-generated) sources, how the syscall number is mapped to that handler (which table file lists it)."

## Required hop chain (3 nodes, 2 edges — all in `fs/read_write.c`)

| # | Hop | Definition site | Call to next hop | Evidence |
|---|-----|-----------------|------------------|----------|
| 1 | `SYSCALL_DEFINE3(read, ...)` | `fs/read_write.c:621` | `fs/read_write.c:623` | Body is a single statement: `return ksys_read(fd, buf, count);` |
| 2 | `ksys_read` | `fs/read_write.c:602` | `fs/read_write.c:613` | `ret = vfs_read(f.file, buf, count, ppos);` (after `fdget_pos(fd)` and `file_ppos()` position setup) |
| 3 | `vfs_read` | `fs/read_write.c:450` | (terminal) | `ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)` — checks FMODE_READ/FMODE_CAN_READ/access_ok, `rw_verify_area`, then dispatches to `file->f_op->read` or `new_sync_read` |

Evidence quotes (verbatim from `fs/read_write.c`):

```c
/* line 621 */ SYSCALL_DEFINE3(read, unsigned int, fd, char __user *, buf, size_t, count)
/* line 622 */ {
/* line 623 */ 	return ksys_read(fd, buf, count);
/* line 624 */ }
```

```c
/* line 602 */ ssize_t ksys_read(unsigned int fd, char __user *buf, size_t count)
...
/* line 613 */ 		ret = vfs_read(f.file, buf, count, ppos);
```

```c
/* line 450 */ ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)
```

There are **no other named function hops on the path** between the syscall definition and `vfs_read()`. (`fdget_pos`/`file_ppos` are subsidiary calls inside `ksys_read`, not hops toward `vfs_read`; the `__x64_sys_read`/`__se_sys_read`/`__do_sys_read` symbols are macro-generated identifiers, not separate in-source function sites.)

## Syscall-number mapping (in-tree, non-generated)

**Table file**: `arch/x86/entry/syscalls/syscall_64.tbl`, **line 11** (verbatim, tab-separated):

```
0	common	read			sys_read
```

Format documented in the same file's header (lines 4–7): `<number> <abi> <name> <entry point>`, and line 7 states: `# The __x64_sys_*() stubs are created on-the-fly for sys_*() system calls`.

So syscall number **0** with ABI `common` maps `read` to entry point **`sys_read`**.

### How `SYSCALL_DEFINE3(read, ...)` produces `sys_read` (macro mechanism, in-tree)

- `include/linux/syscalls.h:221` — `#define SYSCALL_DEFINE3(name, ...) SYSCALL_DEFINEx(3, _##name, __VA_ARGS__)`
- `include/linux/syscalls.h:228-230` — `SYSCALL_DEFINEx(x, sname, ...)` expands to `SYSCALL_METADATA(...)` + `__SYSCALL_DEFINEx(x, sname, ...)`.
- Generic fallback `__SYSCALL_DEFINEx` (`include/linux/syscalls.h:240`) would emit `asmlinkage long sys_read(...)` aliased to `__se_sys_read`, but **on x86 it is overridden**: `arch/x86/include/asm/syscall_wrapper.h:228-240` defines `__SYSCALL_DEFINEx(x, name, ...)` to emit `__X64_SYS_STUBx` (line 231) → `arch/x86/include/asm/syscall_wrapper.h:96` (`__X64_SYS_STUBx`) → `__SYS_STUBx` (line 74), producing `long __x64_sys_read(const struct pt_regs *regs)` that unpacks registers via `SC_X86_64_REGS_TO_ARGS` (line 56) and calls `__se_sys_read` → inlined `__do_sys_read` (the visible `SYSCALL_DEFINE3` body at `fs/read_write.c:621`).
- The table is knit into the kernel in-tree at `arch/x86/entry/syscall_64.c:14-18`: `#define __SYSCALL(nr, sym) __x64_##sym,` then `asmlinkage const sys_call_ptr_t sys_call_table[] = { #include <asm/syscalls_64.h> };` (line 16). Note `asm/syscalls_64.h` itself is **build-generated** from the `.tbl` (`arch/x86/entry/syscalls/Makefile:53-54`) — answers must cite `syscall_64.tbl` as the mapping source, not the generated header.

## Dispatch mechanism (high level — bonus context, not required)

- HW entry: `entry_SYSCALL_64` — `arch/x86/entry/entry_64.S:87`; `call do_syscall_64` at `arch/x86/entry/entry_64.S:120`.
- `do_syscall_64` — `arch/x86/entry/common.c:73` → `do_syscall_x64` — `arch/x86/entry/common.c:40` → `regs->ax = sys_call_table[unr](regs);` — `arch/x86/entry/common.c:50`.
- `sys_call_table[]` definition — `arch/x86/entry/syscall_64.c:16`.
- Entry 0 of that table is `__x64_sys_read`, closing the loop: `syscall(0)` → `entry_SYSCALL_64` → `do_syscall_64` → `sys_call_table[0]` = `__x64_sys_read` → `__se_sys_read`/`__do_sys_read` (= `SYSCALL_DEFINE3(read,...)` body) → `ksys_read` → `vfs_read`.

## Version flag

`x64_sys_call()` (the switch-based dispatcher) **does not exist in v6.6** — it was introduced in v6.9 for the BHI mitigation. An answer citing `x64_sys_call` as a v6.6 hop is a **wrong extra hop** (penalize). In v6.6 the dispatch is the `sys_call_table[unr](regs)` indirect call shown above.

## Question-text check

No defects. The question is answerable entirely from in-tree sources; the required chain is short (one intermediate hop, `ksys_read`) and unambiguous; "the VFS helper" clearly denotes `vfs_read()`. The "non-generated" constraint is meaningful: the tempting citations `asm/syscalls_64.h` and `arch/x86/include/generated/uapi/asm/unistd_64.h` are build products, while `syscall_64.tbl` is the in-tree source of truth.

## Scoring rubric (0-3)

**Required elements** (for full credit):
1. `SYSCALL_DEFINE3(read, ...)` at `fs/read_write.c:621` (±3 lines tolerated).
2. `ksys_read` at `fs/read_write.c:602` (call site 623 → 613 chain implied or stated).
3. `vfs_read` at `fs/read_write.c:450` as the terminal hop.
4. Mapping source: `arch/x86/entry/syscalls/syscall_64.tbl` (line 11: `0 common read sys_read`; naming the file and the `read → sys_read` row suffices).
5. Macro mechanism: `SYSCALL_DEFINE3` generates the `sys_read` entry point (evidence from `include/linux/syscalls.h:221`/`:228` and/or `arch/x86/include/asm/syscall_wrapper.h:228`).

**Scores**:
- **3** — All five required elements with correct file:line for the three hops; no incorrect extra hops. Correct bonus hops (`entry_SYSCALL_64`, `do_syscall_64`, `do_syscall_x64`, `sys_call_table`, `__x64_sys_read` stub) do not affect the score except as tie-breakers upward.
- **2** — Correct 3-hop chain and correct table file, but one required element weak: a missing/imprecise file:line (off by >3 lines), or macro mechanism asserted without in-tree evidence.
- **1** — Chain correct by function names only (locations missing/wrong), or table file missing/replaced by a generated file (`asm/syscalls_64.h`, `generated/.../unistd_64.h`) as the claimed mapping source.
- **0** — Wrong chain (e.g., omits `ksys_read`, routes through `new_sync_read` before `vfs_read`, or invents hops), or wrong table.

**Penalties** (subtract 1, floor 0): each wrong extra hop asserted as part of the v6.6 path — e.g., `x64_sys_call` (v6.9+ only), a standalone in-source `sys_read()` C function definition (does not exist; only the macro-generated alias/stub), or `SyS_read` (pre-4.17 naming).
