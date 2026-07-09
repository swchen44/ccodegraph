# GT — LKQ-060 (include-dependency, L2)

## Question (verbatim)

> For vfs_read: give (a) the header file:line where it is DECLARED (prototype), and (b) the file:line where it is DEFINED (function body). Label which is which explicitly, and name the header a typical caller includes to obtain the declaration. If the declaration is NOT in a public header (e.g. it lives in an fs-internal header), report that accurately instead of assuming linux/fs.h.

Repo: `/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6` (verified `Makefile`: VERSION=6, PATCHLEVEL=6, SUBLEVEL=0).

## Answer

### (a) DECLARATION (prototype) — exactly one site in the tree

**`include/linux/fs.h:1964`**

```c
extern ssize_t vfs_read(struct file *, char __user *, size_t, loff_t *);
```

Verification: a whole-tree grep over all `*.h` files for `vfs_read` yields only this
line (plus the unrelated symbol `ksmbd_vfs_read` in `fs/smb/server/vfs.h:79`).
There is **no** declaration in `fs/internal.h` in v6.6 — grep of `fs/internal.h`
for `vfs_read`/`vfs_write` returns nothing. Adjacent context in `linux/fs.h`
(line 1965) declares `vfs_write` the same way, confirming both still live in the
public header at this version.

Header a typical caller includes: **`<linux/fs.h>`**.

### (b) DEFINITION (function body)

**`fs/read_write.c:450`** (body spans lines 450–479)

```c
ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)
{
	ssize_t ret;

	if (!(file->f_mode & FMODE_READ))
		return -EBADF;
	...
```

### Public vs. internal verdict

In v6.6 the `vfs_read` prototype **IS in the public header `include/linux/fs.h`**
(line 1964). The question's escape hatch ("if it lives in an fs-internal header,
report that") does **not** apply at this version. Note for graders: in later
kernels the `vfs_read`/`vfs_write` prototypes were moved out of `linux/fs.h`
into `fs/internal.h`, so an answer citing `fs/internal.h` reflects a different
kernel version, not v6.6 — it is wrong for this repo.

### Export status (relevant context for "public")

`vfs_read` is **NOT EXPORT_SYMBOL'd** in v6.6. Evidence: `grep EXPORT_SYMBOL
fs/read_write.c` lists `kernel_read` (line 448, immediately before `vfs_read`),
`kernel_write`, `vfs_iter_read`, etc. — no `EXPORT_SYMBOL(vfs_read)` anywhere in
the tree. So `vfs_read` is:

- visible to all **built-in** code via `<linux/fs.h>` (public prototype), but
- **not callable from loadable modules** (no export; modules are directed to
  `kernel_read()`, which is exported at `fs/read_write.c:448`).

This nuance ("declared in a public header, yet not module-exported") is the
expected top-tier observation.

## Question-text notes / flags

- The question is well-posed for v6.6. Its warning against "assuming linux/fs.h"
  is a deliberate trap-check: at v6.6 the assumption happens to be **correct**,
  but only source verification proves it. An answer that says "it's in
  fs/internal.h, not linux/fs.h" (importing knowledge of later kernels) fails
  the verify-at-source requirement.
- Only one declaration site exists; answers listing extra "declaration sites"
  (e.g., `ksmbd_vfs_read`) are confusing a different symbol.

## Rubric (0–3)

- **3** — Declaration at `include/linux/fs.h:1964` AND definition at
  `fs/read_write.c:450` (±2 lines tolerated if clearly the same function),
  both labeled correctly; names `<linux/fs.h>` as the include; correctly states
  the prototype is in the public header (not fs/internal.h). Mentioning the
  no-EXPORT_SYMBOL nuance is a plus but not required for 3.
- **2** — Both files correct and labeled, but a line number wrong/missing, or
  hedges incorrectly about fs/internal.h while still giving linux/fs.h as
  primary.
- **1** — Only one of declaration/definition correct (e.g., definition file
  right but claims declaration is in fs/internal.h, or vice versa), or
  decl/def labels swapped.
- **0** — Wrong files, or asserts the declaration is not in any public header.
- Note on "asserting linux/fs.h without checking": the assertion is factually
  correct for v6.6, so it cannot be penalized on outcome; grade on the stated
  locations and characterization per source shown above.

## Evidence log

```
$ grep -rn "vfs_read" <repo> --include="*.h" | grep -v "vfs_readlink\|vfs_readv"
include/linux/fs.h:1964:extern ssize_t vfs_read(struct file *, char __user *, size_t, loff_t *);
fs/smb/server/vfs.h:79:int ksmbd_vfs_read(...)        # different symbol

$ grep -n "vfs_read\|vfs_write" fs/internal.h
(no output)

$ grep -n "ssize_t vfs_read" fs/read_write.c
450:ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)

$ grep -rn "EXPORT_SYMBOL(vfs_read)" fs/
(no output; nearest: fs/read_write.c:448 EXPORT_SYMBOL(kernel_read))
```
