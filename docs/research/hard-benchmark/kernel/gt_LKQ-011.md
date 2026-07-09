# GT — LKQ-011 (references-usages, L2)

**Repo:** Linux kernel v6.6 (`VERSION=6 PATCHLEVEL=6 SUBLEVEL=0`), read-only checkout at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/linux-v6.6`

## Question (verbatim)

> "Find every call to copy_from_user() in exactly two files: drivers/char/mem.c and drivers/char/random.c. For each call site give file:line, the enclosing function, and the destination buffer expression. State the exact per-file totals. Exclude comments and any *_copy_from_user variants."

## Scope and rules applied

- Exactly two files: `drivers/char/mem.c`, `drivers/char/random.c`. Nothing else counted.
- Counted only bare `copy_from_user(` calls. Excluded: `_copy_from_user`, `__copy_from_user`,
  `raw_copy_from_user`, `unsafe_copy_from_user`, `copy_from_user_nofault`, `copy_struct_from_user`,
  and any other `*copy_from_user*` variant token.
- Excluded comment/string mentions (verified via comment- and string-stripped scan).

## Verification (two independent methods, results identical)

1. **Word-boundary grep** — `grep -n '\bcopy_from_user\b'` on each file, plus a broad
   `grep -nE '[A-Za-z_]*copy_from_user[A-Za-z_]*'` variant sweep, plus a multi-line-split check
   (`grep -nE 'copy_from_user$'`): mem.c → 1 hit (line 242); random.c → 0 hits, 0 variant tokens.
2. **Comment/string-stripped tokenizer (Python)** — removed `/*...*/`, `//...`, string and char
   literals, then matched `(?<![A-Za-z0-9_])copy_from_user\s*\(`: mem.c → 1 (line 242);
   random.c → 0. Variant-token sweep on the stripped source: mem.c → only the bare token at 242;
   random.c → none.

Each hit's surrounding code was read to attribute the enclosing function and classify genuinely.

## Results

### drivers/char/mem.c — total: 1

| # | file:line | Enclosing function | Destination buffer expression | Context |
|---|-----------|--------------------|-------------------------------|---------|
| 1 | drivers/char/mem.c:242 | `write_mem()` (static ssize_t, `/dev/mem` write handler, defined at line 189) | `ptr` (kernel virtual pointer from `xlate_dev_mem_ptr(p)`) | `copied = copy_from_user(ptr, buf, sz);` inside the `while (count > 0)` page-by-page loop, `allowed == 1` branch |

### drivers/char/random.c — total: 0

Zero occurrences of `copy_from_user` in any form (bare call, variant, comment, or string) in
v6.6's `drivers/char/random.c`.

**Why:** since the v5.18 random-driver rewrite, `random.c` uses the iov_iter API. The user-to-kernel
copy path is `copy_from_iter(block, sizeof(block), iter)` at `drivers/char/random.c:1410` inside
`write_pool_user()` (reached from `random_write_iter()` / `random_ioctl()` RNDADDENTROPY). Small
scalar reads from userspace use `get_user()` (lines 1486, 1500, 1504); output paths use
`copy_to_iter()` / `put_user()`. None of these are `*copy_from_user` variants — the symbol is
simply absent.

## Excluded-variant hits

None. Neither file contains any `*_copy_from_user` variant, nor any comment/string mention of
`copy_from_user`. (The only excluded-category candidates checked: `_copy_from_user`,
`__copy_from_user`, `raw_copy_from_user`, `unsafe_copy_from_user`, `copy_from_user_nofault` —
zero hits for all, in both files.)

## FLAG — question premise vs. source

The question presupposes calls exist in both files ("Find every call ... in exactly two files").
In v6.6, `drivers/char/random.c` has **zero** `copy_from_user` occurrences of any kind. This is
not a counting subtlety; the symbol does not appear in the file. A correct answer must
affirmatively state random.c = 0 (and ideally explain the `copy_from_iter` migration) rather than
hallucinate call sites. Answers inventing random.c hits (e.g. attributing the old pre-5.18
`write_pool()` code) are wrong for this repo snapshot.

## Rubric (0–3)

- **3** — Reports mem.c total = 1 with the exact site `drivers/char/mem.c:242`, enclosing function
  `write_mem`, destination expression `ptr`; explicitly states random.c total = 0 (no call sites);
  no invented hits, no variant leakage.
- **2** — Correct mem.c site (line within ±2 or function+expression correct) and states random.c
  has none, but one detail is off (e.g. wrong dest expression, off line number, or vague
  "no results found" without committing to 0).
- **1** — Finds the mem.c call but hallucinates ≥1 random.c call site, OR misses mem.c:242 while
  correctly reporting random.c = 0.
- **0** — Wrong on both files, or fabricates multiple call sites, or counts variants/comments.

Key facts for grading: mem.c = **1** (242, `write_mem`, dest `ptr`); random.c = **0** (uses
`copy_from_iter` at 1410 instead).
