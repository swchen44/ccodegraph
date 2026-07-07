# GT WRQ-021: scan-trigger failure return paths in driver_nl80211.c (SCOPE TRAP)

**Question (verbatim):** "A user reports wpa_supplicant returning a generic
'scan failed' error from the nl80211 driver backend. Find the function(s) in
src/drivers/driver_nl80211.c that construct scan-trigger failure return
paths, and list the distinct conditions under which each returns an error
for a scan request."

**Category:** bug-localization · **Difficulty:** L3

## Why this is a scope trap

The question names one specific file — `src/drivers/driver_nl80211.c` — and
asks for the function(s) **in that file**. This is a genuine, deliberate
scope limiter, not incidental phrasing. In this checkout, the nl80211 driver
backend was split across multiple translation units years ago:

```
$ ls src/drivers/ | grep nl80211
driver_nl80211_android.c
driver_nl80211_capa.c
driver_nl80211_event.c
driver_nl80211_monitor.c
driver_nl80211_scan.c      <-- scan logic lives here
driver_nl80211.c           <-- 8813 lines, the "main" file
driver_nl80211.h
```

All the actual scan-trigger construction logic — building the
`NL80211_CMD_TRIGGER_SCAN` netlink message, handling SSID/frequency/MAC
lists, sending it, and handling the AP-mode retry dance — lives in
**`src/drivers/driver_nl80211_scan.c`**, not in `driver_nl80211.c`. This is
confirmed at the build-system level too: `src/drivers/drivers.mak` lists
`driver_nl80211_scan.o` as its own object (line 31), built as a **separate
translation unit** from `driver_nl80211.o` (line 27) — it is declared via
`driver_nl80211.h` (`int wpa_driver_nl80211_scan(...)`, header line 267) and
linked in, not `#include`d as text into `driver_nl80211.c`.

`src/drivers/driver_nl80211.c` itself contains exactly **one** function that
touches the scan-trigger path, and it has **zero independent error
conditions of its own** — it is a three-line forwarding wrapper. A rigorous
answer must say this plainly, rather than either (a) claiming
`driver_nl80211.c` has no scan function at all (wrong — the wrapper exists
and is the registered driver-ops callback), or (b) silently attributing the
real conditions (found in `driver_nl80211_scan.c`) to `driver_nl80211.c`
without flagging the file split (a scope violation — exactly the kind of
mistake this benchmark's evaluation notes warn against).

## Method

Investigated the real checkout at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/wpa_supplicant`. First
read `gt_case1_driver_ops.txt` for prior context: it documents the
`wpa_driver_nl80211_ops` struct literal in this same file and already
records `scan2 -> driver_nl80211_scan2` as the scan-op mapping (list entry
6/96), confirming the wrapper's name ahead of a fresh grep.

1. `grep -n "^static int driver_nl80211_scan2\|^static int nl80211_scan"
   src/drivers/driver_nl80211.c` → one hit: `driver_nl80211.c:7223`.
2. Read the full function body (`driver_nl80211.c:7223-7228`):
   ```c
   static int driver_nl80211_scan2(void *priv,
                                   struct wpa_driver_scan_params *params)
   {
       struct i802_bss *bss = priv;
       return wpa_driver_nl80211_scan(bss, params);
   }
   ```
   This is the entire function — a single `return` statement forwarding to
   `wpa_driver_nl80211_scan(bss, params)`, no branching, no local error
   conditions.
3. `grep -n "wpa_driver_nl80211_scan\b" src/drivers/driver_nl80211.c` → only
   two hits, both call sites (`driver_nl80211.c:3020` inside an unrelated
   function, and the wrapper at `driver_nl80211.c:7227`) — **no definition**
   of `wpa_driver_nl80211_scan` exists in this file.
4. `grep -n "wpa_driver_nl80211_scan\b" src/drivers/driver_nl80211.h` → line
   267, a declaration only (`int wpa_driver_nl80211_scan(struct i802_bss
   *bss, struct wpa_driver_scan_params *params);`).
5. `grep -n "^int wpa_driver_nl80211_scan" src/drivers/driver_nl80211_scan.c`
   → line 214: the real definition lives in the sibling file.
6. Confirmed the build-system split: `src/drivers/drivers.mak:27` and `:31`
   list `driver_nl80211.o` and `driver_nl80211_scan.o` as separate `DRV_OBJS`
   entries — no `#include "driver_nl80211_scan.c"` anywhere in
   `driver_nl80211.c` (checked directly), so this is a real link-time split,
   not a textual-inclusion illusion.
7. Also checked whether any other scan-adjacent function is defined in
   `driver_nl80211.c` itself: `grep -n "^static.*scan"` turns up only
   `driver_nl80211_scan2` (line 7223) and `scan_state_str` (line 7355, a
   pure debug-string helper for `enum scan_states` used in event/status
   logging — it returns string literals, never an error code, and is
   unrelated to triggering a scan). `.sched_scan` in the ops struct
   (`driver_nl80211.c:8710`) points directly at
   `wpa_driver_nl80211_sched_scan` with **no wrapper function at all** in
   `driver_nl80211.c` — scheduled scan doesn't even get a forwarding shim
   here, reinforcing that scan logic was deliberately centralized in
   `driver_nl80211_scan.c`.
8. For completeness, read `wpa_driver_nl80211_scan` (`driver_nl80211_scan.c:
   214-304`) and its helper `nl80211_scan_common` (`driver_nl80211_scan.c:
   106-205`) in full, to document what the "generic scan failed" error the
   user sees actually traces back to — clearly labeled below as living in
   the *other* file, not `driver_nl80211.c`.

## Result

### Function(s) actually in `src/drivers/driver_nl80211.c`

Exactly **one**: `driver_nl80211_scan2` (`driver_nl80211.c:7223-7228`), the
`.scan2` callback registered in `wpa_driver_nl80211_ops`. It has **no
distinct error conditions of its own** — it unconditionally returns whatever
`wpa_driver_nl80211_scan()` returns (0 on success, negative/`-1` on
failure). There is nothing else to enumerate inside this file: no
validation, no branching, no additional `return -X;` statement anywhere in
the function.

### Where the real conditions live (for context — NOT in driver_nl80211.c)

The substantive scan-trigger failure logic that actually produces the
generic "scan failed" the user sees is in `wpa_driver_nl80211_scan()`,
`src/drivers/driver_nl80211_scan.c:214-304`, plus its helper
`nl80211_scan_common()` at `driver_nl80211_scan.c:106-205`. Distinct error
paths there:

1. **`TEST_FAIL()` injected failure** — `driver_nl80211_scan.c:224-225`:
   `if (TEST_FAIL()) return -1;`. Build-conditional: `TEST_FAIL()` expands to
   `testing_test_fail()` only when both `WPA_TRACE_BFD` and
   `CONFIG_TESTING_OPTIONS` are defined (`src/utils/os.h:657-661`); otherwise
   it's a compile-time `0` and this branch is dead code in a normal build.
2. **Message-construction failure inside `nl80211_scan_common()`** —
   `driver_nl80211_scan.c:227-229`: `msg = nl80211_scan_common(...); if
   (!msg) return -1;`. `nl80211_scan_common()` returns `NULL` (its `fail:`
   label, `driver_nl80211_scan.c:202-204`) if any of the following fail
   while building the `NL80211_CMD_TRIGGER_SCAN` netlink message:
   - initial `nl80211_cmd_msg()` allocation fails (line 115-117)
   - `nla_nest_start()` for the SSID list fails, or any `nla_put()` for an
     individual SSID fails (lines 122-131)
   - `nla_put()` for `extra_ies` fails (lines 139-141)
   - `nla_nest_start()` for the frequency list fails, or any
     `nla_put_u32()` for a frequency fails (lines 146-153)
   - `nla_put()` for a randomized MAC address or MAC mask fails (lines
     182-192, only when `params->mac_addr_rand` is set)
   - `nla_put_u32()` for the aggregated `scan_flags` attribute fails (lines
     196-198)
3. **P2P-probe rate-mask attribute construction failure** —
   `driver_nl80211_scan.c:231-252`: when `params->p2p_probe` is set,
   `nla_nest_start()`/`nla_put()`/`nla_put_flag()` for the suppressed-rates
   attribute can fail, jumping to the function's own `fail:` label
   (line 301-303) and returning `ret`, which is still `-1` at that point.
4. **Kernel/netlink rejected the scan trigger** —
   `driver_nl80211_scan.c:255-281`: `ret = send_and_recv_msgs(drv, msg,
   NULL, NULL);` — this is the actual `NL80211_CMD_TRIGGER_SCAN` request
   sent to the kernel. If `ret` is nonzero (a negative errno returned by the
   kernel/nl80211, e.g. `-EBUSY`, `-ENODEV`, `-ENOBUFS`, etc. — logged at
   line 258-259 as "Scan trigger failed: ret=%d (%s)", which is very likely
   the literal source of the user's generic "scan failed" message):
   - **4a.** If the interface is a hostapd AP interface
     (`drv->hostapd && is_ap_interface(drv->nlmode)`, lines 260-278):
     attempts to switch to station mode
     (`wpa_driver_nl80211_set_mode(bss, NL80211_IFTYPE_STATION)`) and retry
     the scan recursively. Returns the **original** nonzero `ret` if either
     the mode switch itself fails (line 267-269) or the retried
     `wpa_driver_nl80211_scan()` call also fails (line 271-274, after
     restoring the old interface mode). If the retry succeeds, `ret` is
     reset to `0` and this is **not** an error path.
   - **4b.** Otherwise (not an AP-mode hostapd interface, line 279-280):
     immediately returns the nonzero `ret` from the kernel with no retry.

Both `wpa_driver_nl80211_scan` and its sibling `wpa_driver_nl80211_sched_scan`
(`driver_nl80211_scan.c:314`) are defined only in `driver_nl80211_scan.c`,
confirming the entire scan subsystem — not just this one function — was
factored out of `driver_nl80211.c`.

## Scoring rubric (0-3)

- **0** — Either (a) claims no scan-related function exists in
  `driver_nl80211.c` at all (misses `driver_nl80211_scan2` entirely), or (b)
  fabricates specific validation/error conditions as if they were written
  inline in `driver_nl80211.c` (e.g. invents SSID-length checks, busy-flag
  checks, or kernel-errno handling as code physically present in
  `driver_nl80211.c` with fictitious line numbers), or (c) names the wrong
  function (e.g. `wpa_driver_nl80211_scan` as if it were defined, not just
  called, in this file) without ever noticing the file split.
- **1** — Correctly identifies `driver_nl80211_scan2`
  (`driver_nl80211.c:7223`) as the scan2 callback, but either treats it as
  having its own list of error conditions (conflating it with
  `wpa_driver_nl80211_scan`'s logic without acknowledging they're in
  different files), or lists conditions from `driver_nl80211_scan.c` while
  asserting/implying they live in `driver_nl80211.c` — i.e. gets the
  function name right but violates the file-scope limiter in the question.
- **2** — Correctly identifies `driver_nl80211_scan2`
  (`driver_nl80211.c:7223-7228`) as the only function in
  `driver_nl80211.c` touching the scan-trigger path, correctly notes it is a
  pure forwarding wrapper with no independent error branching of its own,
  **and** correctly points to `wpa_driver_nl80211_scan()` in
  `driver_nl80211_scan.c` as where the real logic lives — but does not
  enumerate the conditions there in useful distinct detail (e.g. just says
  "it forwards to a function that can fail for various reasons" without
  listing message-construction failure, kernel rejection, P2P-probe
  attribute failure, or the AP-mode retry branch).
- **3** — All of score-2's requirements, **plus** a materially complete
  enumeration of the distinct error conditions in
  `wpa_driver_nl80211_scan()`/`nl80211_scan_common()`
  (`driver_nl80211_scan.c`) with file:line evidence: at minimum (i)
  `nl80211_scan_common()` returning `NULL` from a netlink-attribute build
  failure, (ii) `send_and_recv_msgs()` returning a nonzero kernel/netlink
  errno (the direct source of the generic "scan failed" message, logged at
  `driver_nl80211_scan.c:258-259`), and (iii) the AP-mode-retry sub-branch
  (mode-switch failure or retry failure) vs. the plain non-AP immediate
  failure. Does not need to catch the minor `TEST_FAIL()` build-conditional
  path or the P2P-probe attribute-construction sub-case to earn full credit,
  but must clearly and correctly distinguish which file each thing lives in
  throughout — an answer that is fully correct on content but blurs the
  `driver_nl80211.c` vs. `driver_nl80211_scan.c` distinction should be capped
  at 2, not 3.

### Common wrong answers and likely causes

- Assuming (from training-data familiarity with older wpa_supplicant
  releases, or other forks) that `driver_nl80211.c` is a single monolithic
  file containing all scan logic inline — true in some historical versions,
  **not** true in this checkout, where the scan subsystem was split into
  `driver_nl80211_scan.c` (confirmed via `drivers.mak`'s separate
  `driver_nl80211_scan.o` build target).
- Grepping only for `"scan"` inside `driver_nl80211.c` and stopping at the
  first substantial-looking hit (e.g. `nl80211_dump_scan`-style helpers or
  `scan_state_str`, `driver_nl80211.c:7355`, a debug string function that
  never returns an error code) instead of tracing the actual call target of
  `driver_nl80211_scan2`.
- Reporting `wpa_driver_nl80211_scan` as "the function in
  driver_nl80211.c" based on its declaration in `driver_nl80211.h` (which
  is `#include`d by `driver_nl80211.c`) without checking that a header
  declaration is not the same as a definition in that `.c` file.
