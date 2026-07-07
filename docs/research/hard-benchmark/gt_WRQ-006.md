# GT WRQ-006: every by-name (not called) pass of freq_cmp()

**Category**: caller-callee | **Difficulty**: L3

## Question (verbatim)

> Function freq_cmp() in src/utils/common.c is never called directly. Find every place
> it is passed BY NAME as an argument (not called), and name the calling function and
> call site.

Scope limiter to respect: the question is only about places where the bare symbol
`freq_cmp` (no parens applied to it, i.e. a function-pointer value) is *passed as an
argument* to something else — not about places that call `freq_cmp(...)` directly
(there are none — the question's premise is correct, verified below), and not about
transitive callers of `int_array_sort_unique()` (the function that does the passing).
"Name the calling function and call site" means: identify the enclosing function that
performs the pass, and the exact file:line of that pass — not every caller further up
the call chain.

## Method

1. `grep -rn "freq_cmp" .` across the whole repo (unrestricted, no `--include` filter,
   from repo root) — returns exactly **2 lines total**, both in `src/utils/common.c`:
   - line 873: `static int freq_cmp(const void *a, const void *b)` — the definition itself.
   - line 895: `qsort(a, alen, sizeof(int), freq_cmp);` — the only other occurrence.
2. Confirmed there is no `freq_cmp(...)` direct-call pattern anywhere (i.e. the question's
   premise — "never called directly" — holds): the only two occurrences of the identifier
   in the entire tree are the definition line and the bare-name argument at line 895.
3. Cross-checked with a second, independent pattern: `grep -rniE '\bfreq_cmp\b' .`
   (case-insensitive, word-bounded) from repo root — same 2 lines, no additional hits.
   Also checked `git grep -n "freq_cmp"` (tracked-files-only) — identical 2 lines. All
   three independent search methods agree exactly.
4. Confirmed `freq_cmp` is declared `static` (`src/utils/common.c:873`), i.e. internal
   linkage restricted to this one translation unit. `grep -n "freq_cmp" src/utils/common.h`
   returns nothing — there is no extern declaration anywhere, so no other `.c` file could
   possibly reference it even indirectly (via a prototype). This makes the 2-occurrence
   grep result exhaustive by construction, not just by search luck.
5. Read the surrounding source (`src/utils/common.c:886-901`) to identify the enclosing
   function and confirm the pass is a genuine function-pointer argument (4th arg of
   `qsort`, the comparator slot), not e.g. a string literal or macro stringification:

   ```
   886: void int_array_sort_unique(int *a)
   887: {
   888:     int alen;
   889:     int i, j;
   890:
   891:     if (a == NULL)
   892:         return;
   893:
   894:     alen = int_array_len(a);
   895:     qsort(a, alen, sizeof(int), freq_cmp);
   896:
   897:     i = 0;
   ...
   901: }
   ```

6. Build-system-level check (the failure mode this benchmark round specifically guards
   against): confirmed `src/utils/common.c` is **unconditionally** compiled — no
   `#ifdef`/`#ifndef` wraps either `freq_cmp` or `int_array_sort_unique` inside the file
   (the only conditional-compilation blocks in `common.c` are unrelated `CONFIG_ANSI_C_EXTRA`
   / `CONFIG_NATIVE_WINDOWS` / `UNICODE` guards elsewhere in the file, lines 356-463,
   nowhere near lines 873-901). At the Makefile level, `../src/utils/common.o` is listed
   unconditionally in `wpa_supplicant/Makefile` (`OBJS +=` at line 82, plus `OBJS_p`,
   `OBJS_c`, and `OBJS_priv` variants) with no surrounding `ifdef` guard — `common.c` is
   always compiled into every wpa_supplicant build variant. No build-system exclusion
   applies; the single pass site is live in all standard builds.

## Result: exactly ONE by-name passing site

| # | Calling function | Call site (file:line) | Passed to | Argument position |
|---|-------------------|------------------------|-----------|---------------------|
| 1 | `int_array_sort_unique()` | `src/utils/common.c:895` | `qsort()` | 4th argument (comparator function pointer) |

There is no second site. `freq_cmp` is `static` (internal linkage) and is referenced by
name exactly once outside its own definition, anywhere in the tree.

Note for context (not itself a "passing site," and out of scope per the question's own
framing — it asks for the site that passes `freq_cmp`, not for `int_array_sort_unique`'s
own callers): `int_array_sort_unique()` is itself called from
`wpa_supplicant/scan.c:356`, `wpa_supplicant/scan.c:899`,
`src/utils/utils_module_tests.c:112`, and `src/utils/utils_module_tests.c:234`. These are
two levels removed from `freq_cmp` (they call the sort wrapper, not `freq_cmp` itself,
and they do not name `freq_cmp` at all) and must NOT be listed as answers to this
question — an agent that lists `scan.c` call sites as "places freq_cmp is passed" has
conflated the transitive call chain with the direct by-name pass and should be marked
down (see rubric).

## Correction to the draft evaluation_notes

The draft's claim — "freq_cmp is passed to qsort() inside int_array_sort_unique()" — is
**confirmed correct** and precisely located at `src/utils/common.c:895`. Nothing in the
draft was wrong here; this GT adds the exact line number, the exhaustiveness proof (via
`static` linkage + triple-independent grep), and the build-system check, none of which
the draft note stated explicitly.

## Scoring rubric (0-3)

- **3**: Identifies the single site — calling function `int_array_sort_unique()`,
  file `src/utils/common.c`, line 895 (±1 acceptable), passed to `qsort()` — and states
  or clearly implies this is the *only* such site (e.g., by not fabricating additional
  ones, or by explicitly noting exhaustivity via `static` linkage). Does not confuse this
  with a direct call to `freq_cmp()`.
- **2**: Correctly identifies `int_array_sort_unique()` / `qsort()` / `common.c` as the
  site but line number is off by more than a couple of lines, or omits the file, or
  additionally lists `int_array_sort_unique()`'s own callers (`scan.c` / module tests)
  as if they were also "places freq_cmp is passed" (scope confusion) without otherwise
  getting the core site wrong.
- **1**: Vague answer — e.g. "it's used in qsort somewhere in common.c" with no function
  name or line, or names the right file but wrong function/mechanism (e.g. claims it's
  passed to `bsearch` or a callback table).
- **0**: Says `freq_cmp` is never passed anywhere, or is directly called somewhere
  (contradicting verified fact), or fabricates a call site in an unrelated file, or no
  verifiable file:line evidence given.
