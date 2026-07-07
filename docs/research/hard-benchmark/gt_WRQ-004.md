# GT WRQ-004: real references to `eloop_remove_timeout()` under src/

**Category**: references-usages | **Difficulty**: L2

**Question (verbatim)**: "List every real code reference to eloop_remove_timeout() under
src/, excluding any occurrence inside a string literal (e.g. debug log messages) or comment."

**Scope note**: question says "under src/" — nothing outside `src/` (e.g. `wpa_supplicant/`,
`hostapd/`) counts, even if it existed. Verified separately: there are zero occurrences of
`eloop_remove_timeout` anywhere outside `src/` in this repo, so the scope limiter does not
actually change the answer here — but it was checked, not assumed.

## Method

1. `grep -rn "eloop_remove_timeout" src/` — 10 raw hits, all inside
   `src/utils/eloop.c` and `src/utils/eloop_win.c`. No other file under `src/` mentions the
   symbol at all (it is `static`, not declared in `eloop.h`, so it can't be called from
   outside these two TUs).
2. Read ±5 lines of context around each hit — every one of the 10 is a plain function
   definition or a direct call expression `eloop_remove_timeout(timeout);`. None sit inside a
   `wpa_printf`/`wpa_msg`/other string-literal argument, and none are commented out with `//`
   or `/* */`.
3. Checked preprocessor structure of both files for `#ifdef`/`#if` blocks that might gate any
   of the 10 lines (build-system-level check, not just source grep): in `eloop.c` all the
   `CONFIG_ELOOP_POLL` / `CONFIG_ELOOP_EPOLL` / `CONFIG_ELOOP_SELECT` / `CONFIG_NATIVE_WINDOWS`
   ifdef ranges were enumerated and none overlap lines 652, 674, 702, 1008, 1084 — all five are
   in unconditional code. In `eloop_win.c` the only ifdefs are `#if 0`/`_WIN32_WCE` guards, none
   of which overlap lines 285, 305, 333, 594, 656 — all five are unconditional too.
4. Checked the **build-system level**, not just source text, for the file-selection mechanism:
   `wpa_supplicant/Makefile` sets `CONFIG_ELOOP=eloop` by default and compiles
   `../src/utils/$(CONFIG_ELOOP).o`, i.e. `eloop.c` is what a normal Linux/Unix build compiles.
   `eloop_win.c` is instead pulled in by `wpa_supplicant/nmake.mak` (`eloop_win.obj`) for the
   Windows/MSVC build. Neither file is dead in all configurations — they are two alternate,
   platform-selected implementations of the same eloop backend, each unconditionally live in
   its own target. This is different from the earlier-round trap (a file entirely excluded by
   a Makefile `ifdef` in every build): here both files are real, reachable, compiled sources
   depending on target platform, and the question does not restrict to "the default build" —
   it says "under src/", which both files are. So both sets of 5 are counted as real references.
5. Second independent pass: re-ran the grep, re-diffed against the list below line-by-line,
   and specifically looked for any line containing both a wpa_printf/wpa_msg string mentioning
   "eloop_remove_timeout" AND a real call nearby (the trap called out in the task) — none
   exists; there is no debug string anywhere in the codebase that names this function (it's an
   internal helper, never referenced in log text or comments).

## Real code references (10) — the GT answer

`src/utils/eloop.c` (Unix/select/poll/epoll backend, default build via `CONFIG_ELOOP=eloop`):

| line | kind |
|---|---|
| 652 | function definition: `static void eloop_remove_timeout(struct eloop_timeout *timeout)` |
| 674 | call, inside `eloop_cancel_timeout()` |
| 702 | call, inside `eloop_cancel_timeout_one()` |
| 1008 | call, inside the timeout-expiry dispatch loop in `eloop_run()` |
| 1084 | call, inside `eloop_destroy()` cleanup loop |

`src/utils/eloop_win.c` (Windows event-loop backend, compiled instead of eloop.c only for the
Windows/nmake build):

| line | kind |
|---|---|
| 285 | function definition: `static void eloop_remove_timeout(struct eloop_timeout *timeout)` |
| 305 | call, inside `eloop_cancel_timeout()` |
| 333 | call, inside `eloop_cancel_timeout_one()` |
| 594 | call, inside the timeout-expiry dispatch loop in `eloop_run()` |
| 656 | call, inside `eloop_destroy()` cleanup loop |

Total: **10 real references** (2 definitions + 8 call sites), split 5/5 across the two
alternate backend implementations. No occurrence anywhere else under `src/`.

## Excluded false positives

**None found.** Every one of the 10 raw grep hits under `src/` is a genuine code reference
(a definition or a direct call). There is no `wpa_printf`/`wpa_msg` debug string that names
`eloop_remove_timeout`, and no `//` or `/* */` comment mentions it either. (This is notable in
itself — this question has a "clean" answer set with zero noise to filter, unlike questions
built around symbols that also appear in log strings.)

## Scoring rubric (0–3)

- **3** — Lists all 10 real references (both eloop.c and eloop_win.c, 5 each: 1 definition + 4
  calls per file), with correct file:line, and includes no false positives (no string-literal
  or comment mentions — though none exist to trip on, so also acceptable: correctly reports
  "no false positives found" if it explicitly checked).
- **2** — Finds all 5 references in one file (either eloop.c or eloop_win.c) correctly but
  misses the other file's 5 entirely, OR finds 8-9 of the 10 correct references with no false
  positives.
- **1** — Finds only a handful of the 10 (e.g. only the definition, or only 1-2 call sites in
  one file), or reports the correct set but incorrectly excludes/includes entries based on a
  misunderstanding of the build variant (e.g. claims eloop_win.c "doesn't count" without
  build-system justification, or vice versa incorrectly zeroes out eloop.c).
- **0** — Misses most references, fabricates a string-literal/comment exclusion that doesn't
  exist, confuses `eloop_remove_timeout` with the public API `eloop_cancel_timeout`/
  `eloop_cancel_timeout_one`, or reports references from outside `src/` (scope violation).

Partial credit should subtract for both directions of error: missing real references (recall)
and including anything from outside src/, or any fabricated string/comment exclusion not
actually present (precision).
