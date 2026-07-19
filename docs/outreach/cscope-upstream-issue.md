# cscope upstream issue 草稿

投放目標:**SourceForge bug tracker**(https://sourceforge.net/p/cscope/bugs/,
官方管道)。注意:上游自 2018(15.9)後無 release、tracker 響應低——
發文的主要價值是「可公開引用的記錄」(其他投放稿會連結它),不必期待
回覆。可同場知會:Debian 打包者(tracker.debian.org/pkg/cscope)與
GitHub 社群 fork(portante/cscope)。發文者:使用者本人。

最終檢查(2026-07-19):三類 bug 全部以 **fresh 資料庫 + Homebrew 上游
vanilla 15.9**(formula 無 patch,源碼即 SourceForge tar.gz)重現通過;
Class 2 的行號逐字核對無誤;Class 3 兩例都附上今日可重現指令。

---

**Title:** Line-oriented and -L query results are lossy on larger files: dropped rows, duplicated caller attributions, and drifted line numbers (cscope 15.9)

**Body:**

While building a tool that consumes cscope's cross-reference database, we
differential-tested cscope's own query engine (`-L` / line-oriented mode)
against a direct parse of `cscope.out`. The crossref database itself is
consistently correct; the *query* side shows three reproducible bug
classes on larger real-world files. Verified on cscope 15.9 built from
vanilla upstream source (the Homebrew build on macOS/arm64 — the formula
applies no patches, source is the SourceForge cscope-15.9.tar.gz);
databases built with `-bkR` and `-bckR` (both the compressed and the
uncompressed `-c` format are affected, interestingly dropping *different*
subsets — see class 2).

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

```
cscope -bckR -f cs.out
cscope -d -f cs.out -L3 fst_group_get_id | grep fst_internal
```

reports a hit at `src/fst/fst_internal.h:1255` — that header is only
**49 lines long**; the real site is `fst_session.c:1255` (the adjacent
compilation unit which `#include`s the header). Reproduces on a fresh
database every time in our testing.

A second variant: against the default (compressed) database,
`-L3 os_free` reports a hit at `crypto_internal.c:223` — line 223 is
blank in the source, the crossref has *no record* for line 223, and the
actual call is at line 217 (also reported). Incidentally the same query
illustrates class 2 at larger magnitude: the uncompressed database
returns 10 rows for this file, the compressed one 32.

## Notes

- The crossref database is fine in every case we checked: parsing
  `cscope.out` directly yields the complete, correctly-numbered result
  set. The lossiness is in the query-side scan.
- Full write-up with additional cases and byte-level crossref dumps:
  <https://github.com/swchen44/ccodegraph/blob/main/docs/research/cscope-query-engine-bugs.md>
- Happy to provide more repro data or test patches.
