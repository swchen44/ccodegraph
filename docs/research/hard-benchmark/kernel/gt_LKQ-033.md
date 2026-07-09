# GT — LKQ-033 (callback-indirect, L3)

**Repo:** Linux kernel v6.6 (`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`, tag `v6.6`, Makefile VERSION=6 PATCHLEVEL=6 SUBLEVEL=0)

## Question (verbatim)

> In fs/ext4/file.c find the ext4_file_operations definition (file:line). Map each of these fields to its assigned function and give each function's definition file:line (definitions may live in other ext4 files): .read_iter, .write_iter, .open, .release, .fsync. If any of these five fields is absent from the struct literal, say so explicitly rather than guessing.

## Ground truth

### Struct literal location

`fs/ext4/file.c:950` — `const struct file_operations ext4_file_operations = {`
Full literal spans **fs/ext4/file.c:950–968** (closing `};` at line 968).

Quoted struct literal (lines 950–968):

```c
950	const struct file_operations ext4_file_operations = {
951		.llseek		= ext4_llseek,
952		.read_iter	= ext4_file_read_iter,
953		.write_iter	= ext4_file_write_iter,
954		.iopoll		= iocb_bio_iopoll,
955		.unlocked_ioctl = ext4_ioctl,
956	#ifdef CONFIG_COMPAT
957		.compat_ioctl	= ext4_compat_ioctl,
958	#endif
959		.mmap		= ext4_file_mmap,
960		.mmap_supported_flags = MAP_SYNC,
961		.open		= ext4_file_open,
962		.release	= ext4_release_file,
963		.fsync		= ext4_sync_file,
964		.get_unmapped_area = thp_get_unmapped_area,
965		.splice_read	= ext4_file_splice_read,
966		.splice_write	= iter_file_splice_write,
967		.fallocate	= ext4_fallocate,
968	};
```

### Per-field table

| Field | Present? | Assignment site | Assigned function | Definition site | Signature evidence |
|---|---|---|---|---|---|
| `.read_iter` | **Present** | fs/ext4/file.c:952 | `ext4_file_read_iter` | **fs/ext4/file.c:130** | `static ssize_t ext4_file_read_iter(struct kiocb *iocb, struct iov_iter *to)` |
| `.write_iter` | **Present** | fs/ext4/file.c:953 | `ext4_file_write_iter` | **fs/ext4/file.c:703** (return type `static ssize_t` on line 702; name line 703) | `static ssize_t` / `ext4_file_write_iter(struct kiocb *iocb, struct iov_iter *from)` |
| `.open` | **Present** | fs/ext4/file.c:961 | `ext4_file_open` | **fs/ext4/file.c:878** | `static int ext4_file_open(struct inode *inode, struct file *filp)` |
| `.release` | **Present** | fs/ext4/file.c:962 | `ext4_release_file` | **fs/ext4/file.c:166** | `static int ext4_release_file(struct inode *inode, struct file *filp)` |
| `.fsync` | **Present** | fs/ext4/file.c:963 | `ext4_sync_file` | **fs/ext4/fsync.c:129** (cross-file; declared `extern` in fs/ext4/ext4.h:2836) | `int ext4_sync_file(struct file *file, loff_t start, loff_t end, int datasync)` |

**All five named fields are present in the struct literal.** The correct answer must NOT claim any of them absent.

### Verification notes

- Grep confirmed exactly one `ext4_file_operations` definition in fs/ext4/file.c (line 950); no other struct literal candidates in the file.
- Four of the five handlers are `static` and defined in fs/ext4/file.c itself; only `ext4_sync_file` is cross-file (fs/ext4/fsync.c:129) — this is the L3 "definitions may live in other ext4 files" trap.
- Line-number tolerance: for `ext4_file_write_iter`, accept 702 or 703 (multi-line signature: return type at 702, function name at 703). For all others the name and return type share one line.
- fs/ext4/ext4.h:2836 is a *declaration*, not a definition — an answer citing ext4.h as the definition site of `ext4_sync_file` is wrong.
- Question-text problems: none found. The struct exists in the named file, all five fields are present, and the "absent field" clause is a deliberate distractor (the correct response is to affirm presence of all five).

## Rubric (0–3)

Prerequisite for scoring above 0: locates `ext4_file_operations` at fs/ext4/file.c:950 (accept 950 or the 950–968 span) and does not falsely claim any of the five fields absent.

- **3** — All five fields correctly mapped to their functions AND all five definition sites correct, including the cross-file `ext4_sync_file` → fs/ext4/fsync.c:129. Line numbers within ±3 of GT (write_iter: 702/703 both exact).
- **2** — Exactly one definition site wrong or missing (e.g. cites ext4.h:2836 for ext4_sync_file, omits one file:line, or one line number off by >3), all five field→function mappings still correct.
- **1** — Two or more definition sites wrong/missing, or one field→function mapping wrong, but struct located and majority of mappings correct.
- **0** — Struct not located, ≥2 field→function mappings wrong, or any of the five fields falsely declared absent.
