# cscope upstream issue 草稿

投放目標:cscope 專案(SourceForge bug tracker,或 cscope-devel
mailing list)。純 bug report,附最小重現。發文者:使用者本人。

---

**Title:** Line-oriented and -L query results are lossy on larger files: dropped rows, duplicated caller attributions, and drifted line numbers (cscope 15.9)

**Body:**

While building a tool that consumes cscope's cross-reference database, we
differential-tested cscope's own query engine (`-L` / line-oriented mode)
against a direct parse of `cscope.out`. The crossref database itself is
consistently correct; the *query* side shows three reproducible bug
classes on larger real-world files. Found on cscope 15.9 (Apple clang
build on macOS, also reproduced with the Homebrew build); databases built
with `-bkR` and `-bckR` (both compressed and uncompressed formats affected,
interestingly in *different* ways — see class 3).

All examples below use the wpa_supplicant source tree (any recent
checkout reproduces).

## Class 1: duplicated caller attribution on multi-line definitions

```
cscope -bckR -f cs.out
cscope -d -f cs.out -L3 radius_msg_get_attr_ptr
```

For call sites inside:

```c
static RadiusRxResult
radius_das_disconnect(struct radius_das_data *das, ...)
```

the same call site is reported **twice**, once with the caller
`radius_das_disconnect` (correct) and once with the caller
`RadiusRxResult` (the *return type*). The crossref contains a single,
correct `$radius_das_disconnect` function mark — the duplication happens
in the query engine's caller derivation.

## Class 2: dropped result rows

`src/radius/radius_das.c` contains 8 call sites of
`radius_msg_get_attr_ptr` (crossref records at lines 76, 88, 100, 106,
121, 127, 133, 139 — verifiable by inspecting `cscope.out` directly).
`-L3 radius_msg_get_attr_ptr` returns only 5 of them against the
compressed database, and a *different* subset against the uncompressed
(`-c`) database. Lines 100 and 106 are dropped in both modes.

## Class 3: line-number / file drift

`-L3 os_free` reports a hit at `crypto_internal.c:223` — but line 223 is
blank in the source, the crossref has *no record* for line 223, and the
actual call is at line 217. In an extreme case, `-L3 fst_group_get_id`
attributes a hit to `src/fst/fst_internal.h:1255` — that header is only
49 lines long; the real site is `fst_session.c:1255`.

## Notes

- The crossref database is fine in every case we checked: parsing
  `cscope.out` directly yields the complete, correctly-numbered result
  set. The lossiness is in the query-side scan.
- Full write-up with additional cases and byte-level crossref dumps:
  <https://github.com/swchen44/ccodegraph/blob/main/docs/research/cscope-query-engine-bugs.md>
- Happy to provide more repro data or test patches.
