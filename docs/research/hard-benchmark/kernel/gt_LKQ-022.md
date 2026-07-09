# GT: LKQ-022 (caller-callee, L2)

## Question (verbatim)

> List every function directly called by ksys_read() (defined in fs/read_write.c), in source order, with the call-site line numbers. If something that looks like a call is a macro, say so and identify what it expands to if determinable from the source.

Repo: Linux kernel v6.6 (`repos/linux-v6.6`), file: `fs/read_write.c`.

## Function body (verbatim, fs/read_write.c:602-619)

```c
ssize_t ksys_read(unsigned int fd, char __user *buf, size_t count)
{
	struct fd f = fdget_pos(fd);
	ssize_t ret = -EBADF;

	if (f.file) {
		loff_t pos, *ppos = file_ppos(f.file);
		if (ppos) {
			pos = *ppos;
			ppos = &pos;
		}
		ret = vfs_read(f.file, buf, count, ppos);
		if (ret >= 0 && ppos)
			f.file->f_pos = pos;
		fdput_pos(f);
	}
	return ret;
}
```

## Ground truth: direct callees in source order

Exactly **4** call expressions. None of them is a preprocessor macro — a correct answer must state this negative finding, since the question invites macro identification.

| # | Callee | Call-site line | Classification | Definition site |
|---|--------|----------------|----------------|-----------------|
| 1 | `fdget_pos` | 604 | `static inline` function (not a macro) | `include/linux/file.h:72-75` — body: `return __to_fd(__fdget_pos(fd));` (`__fdget_pos` is a real extern function, `fs/file.c:1057`) |
| 2 | `file_ppos` | 608 | `static inline` function, file-local (not a macro) | `fs/read_write.c:597-600` — returns `&file->f_pos` or `NULL` if `FMODE_STREAM` |
| 3 | `vfs_read` | 613 | ordinary extern function | `fs/read_write.c:450` |
| 4 | `fdput_pos` | 616 | `static inline` function (not a macro) | `include/linux/file.h:77-82` — conditionally calls `__f_unlock_pos(f.file)`, then `fdput(f)` |

Macro check (two-method verified): `grep -rn "#define fdget_pos\|#define fdput_pos\|#define vfs_read\|#define file_ppos"` over `include/` and `fs/` returns nothing; the definitions above were read directly. So there are **no call-lookalike macros** in this body.

## Things that are NOT calls (common traps)

- `f.file` (lines 607, 608, 613, 615) — struct-member access on `struct fd` (`include/linux/file.h:36-39`). v6.6 predates the `fd_file()`/`fd_empty()` accessors (introduced ~v6.12); an answer listing those is anachronistic and wrong for this repo.
- `f.file->f_pos = pos` (line 615) — member access + assignment, not a call. This is the v6.6 inlined equivalent of the old `file_pos_write()`; `file_pos_read()`/`file_pos_write()` helpers do **not exist** in v6.6 (`file_ppos` at line 597 replaced them, commit-lineage: 5dea5c25, v5.2). Answers inventing `file_pos_read`/`file_pos_write` calls are wrong.
- `-EBADF` (line 605) — object-like macro constant (`include/uapi/asm-generic/errno-base.h:13`), does not look like a call; not part of the callee list.
- `SYSCALL_DEFINE3(read, ...)` at line 621 is **outside** `ksys_read()` — it is the caller, not a callee. Including it violates the scope limiter.

## Question-text notes

- The question is well-posed and answerable; no defects found. The macro clause is a deliberate probe: the correct response is "none of the callees is a macro; `fdget_pos`/`fdput_pos`/`file_ppos` are `static inline` functions, `vfs_read` is an ordinary function."

## Rubric (0-3)

- **3** — All 4 callees (`fdget_pos` @604, `file_ppos` @608, `vfs_read` @613, `fdput_pos` @616) in source order with correct line numbers; correctly classifies each (static inline vs ordinary function, none macros) with plausible definition sites; does not list member accesses (`f.file`, `f.file->f_pos`) or `SYSCALL_DEFINE3` as calls. Line numbers ±1 acceptable if the call expression is correctly identified.
- **2** — All 4 callees with correct lines and order, but classification is incomplete or partly wrong (e.g., asserts `fdget_pos` is a macro without evidence, or omits the "no macros" finding), or fails to distinguish member accesses.
- **1** — Misses exactly one real callee (most commonly `file_ppos`) or adds exactly one spurious callee (e.g., `file_pos_read`, `fd_file`, `fput`), with the rest correct.
- **0** — Two or more callees missing or invented, wrong function analyzed, wrong file, or answer built from a different kernel version's body (e.g., `fd_empty`/`fd_file` era).

## Verification methods used

1. Direct read of `fs/read_write.c:595-625` (body quoted above).
2. `grep -n` for each callee's definition: `fdget_pos`/`fdput_pos` in `include/linux/file.h` (lines 72, 77), `vfs_read` in `fs/read_write.c` (line 450), `file_ppos` in `fs/read_write.c` (line 597), `__fdget_pos` in `fs/file.c` (line 1057); plus a repo-wide `#define` negative check for all four names.
