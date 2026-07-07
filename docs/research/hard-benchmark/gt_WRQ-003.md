# GT WRQ-003: definition of struct wpa_driver_ops

Question ID: WRQ-003 (category: symbol-definition, difficulty: L2, repo: wpa)

Question (verbatim):
"Find the definition of struct wpa_driver_ops. Return file, line, and total number of
function-pointer fields."

Repo checkout verified: `wpa_supplicant-2.5` (confirmed via
`src/common/version.h:5` `VERSION_STR "2.5"` and `git log` root commit message
"init from wpa_supplicant-2.5", commit `515eb37`). This is a fixed, non-drifting
snapshot, so field counts below will not change across re-runs of this benchmark.

Method: grepped/read the struct directly from source (not guessed), then ran **three
independent counting passes** that had to agree before finalizing, then separately
checked for build-system-level effects (the exact failure mode this benchmark
guards against per an earlier round's mistake) — i.e. whether any fields are
gated by `#ifdef`/`#ifndef` inside the struct body, and whether this repo's actual
`.config` would compile them in or out.

## Definition — the answer

- **File**: `src/drivers/driver.h`
- **Line**: **1633** — `struct wpa_driver_ops {` (the doc-comment block
  `/** * struct wpa_driver_ops - Driver interface API definition ... */`
  immediately precedes it at lines 1627–1632; either line is a reasonable
  "find the definition" answer, but 1633 is the actual tag/struct-keyword line
  that ctags/clangd/cscope-style goto-definition would land on).
- **Struct body span**: lines 1633–3442 (closing `};` at line 3442) — **1,810 lines**,
  confirming this is the ~130+-field struct the task description warned is easy to
  under-read.
- **Function-pointer fields: 142** (verified three independent ways, see below).
- **Non-function-pointer (plain data) fields: 2** — `const char *name;` (line 1635)
  and `const char *desc;` (line 1637). These are the only two fields in the entire
  struct that are not `(*name)(...)` function pointers.
- **Total fields as written in source: 144** (142 + 2). The question only asks for
  the function-pointer count, so **the number to grade against is 142**, not 144.

## Triple independent verification (must-agree check)

**Pass 1 — raw grep, comments included** (sanity check that no doc-comment
accidentally contains a `(*name)(`-shaped false positive):
```
$ grep -oE '\(\*[a-zA-Z_][a-zA-Z0-9_]*\)\(' <(sed -n '1633,3442p' driver.h) | wc -l
142
$ grep -oE '\(\*[a-zA-Z_][a-zA-Z0-9_]*\)\(' <(sed -n '1633,3442p' driver.h) | sort -u | wc -l
142   # <- all 142 field names are unique, zero duplicates
```

**Pass 2 — Python: strip `/* ... */` block comments with a DOTALL regex, split the
struct body on `;`, classify each remaining statement** as function-pointer (matches
`\(\s*\*\s*\w+\s*\)\s*\(`) or plain data:
```
Total statements (fields): 144
Function pointer fields:   142
Data fields:                 2   -> 'const char *name', 'const char *desc'
```

**Pass 3 — independent line-by-line char-level comment stripper** (tracks
`/*`/`*/` state across line boundaries manually, rather than a single regex over
the whole blob, as a structurally different implementation from Pass 2):
```
Function pointer fields: 142
Data fields: 2
Total: 144
```

All three passes agree exactly: **142 function-pointer fields, 2 data fields, 144
total**. Also confirmed no nested `struct {`/`union {`/`enum {` blocks exist inside
the body (brace-balance check: exactly 1 open `{` and 1 close `}` after comment
stripping, i.e. the outer struct only) — so there is no risk of a nested block's
semicolons corrupting the statement count.

Spot-checked first/last field names with their absolute line numbers to confirm the
window boundaries are right: first field is `get_bssid` at line 1650, last field is
`set_prob_oper_freq` at line 3441 (immediately before the closing `};` at 3442).

## Build-system-level check — conditional-compilation caveat (verified)

Per this benchmark's own precedent of a GT missing a build-gated effect, the struct
body was checked for `#ifdef`/`#endif` blocks, since driver.h is a header (not a
Makefile), a "build-system-level" trap here means preprocessor macros, not a whole
excluded `.c` file:

- `#ifdef ANDROID` … `#endif /* ANDROID */` at lines 2873–2883 gates exactly
  **1** function-pointer field: `driver_cmd`.
- `#ifdef CONFIG_MACSEC` … `#endif /* CONFIG_MACSEC */` at lines 3178–3373 gates
  exactly **21** function-pointer fields: `macsec_init`, `macsec_deinit`,
  `enable_protect_frames`, `set_replay_protect`, `set_current_cipher_suite`,
  `enable_controlled_port`, `get_receive_lowest_pn`, `get_transmit_next_pn`,
  `set_transmit_next_pn`, `get_available_receive_sc`, `create_receive_sc`,
  `create_receive_sa`, `enable_receive_sa`, `disable_receive_sa`,
  `get_available_transmit_sc`, `create_transmit_sc`, `create_transmit_sa`,
  `enable_transmit_sa`, `disable_transmit_sa`, `delete_receive_sc`,
  `delete_transmit_sc`.
- Checked this repo's actual `wpa_supplicant/.config` (the file already present in
  this checkout, alongside pre-existing `.o` build artifacts): it sets
  `CONFIG_AP=y`, `CONFIG_SAE=y`, `CONFIG_IEEE8021X_EAPOL=y`, etc., but **does
  not** set `CONFIG_MACSEC=y`, and there is no `-DANDROID` anywhere in this
  build's flags (that only applies to the separate `android.config`, not the
  `.config` actually used). So **in an actual compiled build of this exact
  checkout, only 142 − 22 = 120 function-pointer fields would exist in the
  compiled struct** (122 total incl. `name`/`desc`).

Unlike the earlier round's mistake (a *whole file* silently excluded from the
build, invisible unless you read the Makefile), here the gated fields are fully
visible in a plain read of `driver.h` — they are inline `#ifdef` blocks inside the
one file the question points at, not hidden in a different file. Since the
question says "find the definition of struct wpa_driver_ops" with no build-config
qualifier (e.g. it does not say "as compiled with the default `.config`"), the
natural, defensible reading is the struct's **textual/source-level definition**,
which is what a `grep`/read-based tool (or a human) would report: **142**
function-pointer fields. The 120-under-actual-.config figure is documented above
as a bonus-rigor fact, not a competing "correct" answer — but an answer that
explicitly surfaces the ANDROID/CONFIG_MACSEC conditional split (142 written vs.
120 as configured) demonstrates *more* rigor than a bare "142" and should not be
penalized for mentioning it.

## Correction to the draft evaluation_notes ("Correct field count is 136")

The draft `evaluation_notes` for WRQ-003 claims "Correct field count is 136." This
is **wrong** — verified wrong by three independent counting methods above, all of
which converge on **142** (or 144 if the two non-function-pointer fields are
included). There is no field-count reading of this struct in this exact checkout
that produces 136: not the full source count (142), not the "as-configured"
compiled count (120), not the total-including-data-fields count (144).

The same suspect "136" figure also appears verbatim in the header comment of the
related file `gt_case1_driver_ops.txt` ("96 of 136 struct fields" — the nl80211
backend's populated `wpa_driver_nl80211_ops` struct *literal*, a different
question about which fields nl80211 fills in, not this question about the struct
*definition*). Since both notes cite the identical wrong number, "136" almost
certainly originated from one earlier, never-re-verified hand count that was
copied across both draft documents rather than two independently-wrong counts.
`gt_case1_driver_ops.txt` is useful cross-reference for *which* fields nl80211
populates (96 of them), but its "136" denominator should be treated as suspect
for the same reason and is **not** authoritative for WRQ-003 — this file (built
from direct, triple-checked source counts) supersedes it for the definition
question.

## Scoring rubric (0–3)

- **Score 3**: File `src/drivers/driver.h`, line in the 1627–1633 range (doc-comment
  start through the `struct wpa_driver_ops {` line), **and** function-pointer field
  count = **142 exactly**. An answer that additionally notes the `#ifdef
  ANDROID`/`#ifdef CONFIG_MACSEC` conditional fields (1 + 21 = 22) and gives both the
  142-written and 120-as-configured figures is still a 3 (extra rigor, not an error).
- **Score 2**: Correct file and line, but field count is off by a small amount
  (roughly ±1 to ±10, e.g. 136, 140, 141, 143, 144, 150) — this is exactly the
  "off-by-a-few" signature the benchmark's own evaluation intent flags as evidence
  of not reading the *entire* ~1,800-line struct top to bottom (e.g. stopping
  before the MACsec block near the end, or double-counting the 2 data fields into
  the function-pointer count). An answer of exactly **136** (matching the flawed
  draft) falls here — it is not "correct because the draft said so," it is
  demonstrably wrong by 6 and should be scored as a partial/incomplete read, same
  as any other off-by-a-few answer.
- **Score 1**: Correct file, but field count is wildly off (>10 away and not
  explained by a coherent conditional-compilation argument — e.g. claims ~90-100
  fields, suggesting confusion with the nl80211 *populated-literal* count from
  `gt_case1_driver_ops.txt` rather than the struct *definition*), or the line
  number points somewhere clearly wrong within the file (e.g. inside the struct
  body rather than its start, or at an unrelated `wpa_driver_ops::` doc-comment
  cross-reference elsewhere in the file, such as line 1627/3490/4702's mentions).
- **Score 0**: Wrong file entirely (e.g. a different driver-ops-like struct, or a
  hostapd equivalent), fabricated line number, or no verifiable file:line evidence
  given.
