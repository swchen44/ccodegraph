# GT WRQ-005: real references to decrRefCount() within src/t_string.c only

**Category**: references-usages | **Difficulty**: L2

## Question (verbatim)

> List every real code reference to decrRefCount() within src/t_string.c only, excluding comments.

Scope limiter to respect: **"within src/t_string.c only"** — references to `decrRefCount`
in any other file (e.g. `t_string.h`, `object.c`, other command files) must NOT be counted,
even though `decrRefCount` is a globally-used Redis primitive called from dozens of files.
This GT only enumerates hits inside `src/t_string.c` of this checkout.

## Method

1. `grep -n "decrRefCount" src/t_string.c` — 8 total line matches.
2. Cross-check with `awk '/decrRefCount/{print NR}' src/t_string.c | wc -l` — also 8. Counts agree.
3. Manually read the surrounding source (not just the matched line) for every hit to classify
   as real call vs. comment vs. disabled code.
4. Checked for build-system-level gating: `grep -n '^#if\|^#ifdef\|^#ifndef\|^#else\|^#endif' src/t_string.c`
   returned **no matches** — the file has no conditional-compilation blocks at all, so none of
   the 8 lines are inside an `#ifdef`/`#if 0` block. No build-system effect applies here (unlike
   cases where a whole file/function is Makefile- or macro-gated).

## Result: 7 real code references, 1 excluded comment

| # | Line | Snippet | Classification |
|---|------|---------|-----------------|
| 1 | 128 | `decrRefCount(current_decoded);` | real call — frees decoded object after IFEQ/IFNE comparison in `setGenericCommand` |
| — | 186 | `* and will call decrRefCount() at the end of call(). We increment the refcount` | **excluded — inside a `/* ... */` block comment** (part of a multi-line comment explaining refcounting semantics; not executable code) |
| 2 | 207 | `decrRefCount(milliseconds_obj);` | real call — frees temp object in `setGenericCommand` after command rewrite |
| 3 | 543 | `decrRefCount(milliseconds_obj);` | real call — `getexCommand` |
| 4 | 894 | `decrRefCount(milliseconds_obj);` | real call — `msetexCommand` |
| 5 | 1347 | `decrRefCount(milliseconds_obj);` | real call — `increxCommand` |
| 6 | 1629 | `if (obja) decrRefCount(obja);` | real call — `lcsCommand` cleanup label, conditional call |
| 7 | 1630 | `if (objb) decrRefCount(objb);` | real call — `lcsCommand` cleanup label, conditional call |

**Total real references = 7. Excluded comment = 1 (line 186).**

Note: the line number for the excluded comment is **186** in this checkout (the draft
evaluation_notes said "near line 186" — this is confirmed exact, not drifted, in this
checkout of the repo). Lines 1629/1630 are two separate reference lines (one call each,
each individually `if`-guarded) — do not collapse them into a single reference or split
them further; they are two distinct statements on two distinct lines.

Cross-reference: this matches and is consistent with `gt_case4_lifecycle.md`, which
independently identified `decrRefCount` call sites at lines 207, 543, 894, 1347, 1629,
1630 as the "locally freed" pairing points for `createStringObjectFromLongLong` /
`createStringObject("",0)` allocations in this same file. That doc did not track line 128
(the IFEQ/IFNE decoded-object free) or line 186 (the comment) because its scope was
specifically the createStringObject*/decrRefCount lifecycle pairing, not an exhaustive
decrRefCount census — this GT's exhaustive count of 7 is the superset relevant here.

## Scoring rubric (0-3)

- **3**: Reports exactly 7 real references (all of lines 128, 207, 543, 894, 1347, 1629, 1630,
  or an equivalent unambiguous list/count of 7), AND correctly excludes line 186 as a comment
  (either by omission or by explicitly noting the exclusion). No references from other files
  included.
- **2**: Correct total count of 7 real references but list has minor errors (e.g., off-by-one
  line number reported, or 1629/1630 merged into one bullet without changing the count), OR
  correctly lists all 7 but fails to mention/notice the excluded comment at line 186 when the
  question implies awareness of it, OR includes 1 extraneous non-t_string.c reference alongside
  an otherwise-correct list.
- **1**: Finds most (4-6) of the real references but misses one or more, OR incorrectly counts
  the line-186 comment as a real reference (fails the "excluding comments" instruction), OR
  includes multiple references from other files (violates the "within src/t_string.c only" scope).
- **0**: Substantially wrong — wrong file, wrong function, count far off (e.g. <4 or includes
  fabricated line numbers), or no meaningful attempt to distinguish comments from real calls.
