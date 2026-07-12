# r/C_Programming 投放稿

角度:cscope bug 發現 + no-build C 索引器;C 工具人群向,AI 內容降權。

---

**Title:** TIL cscope's query engine (-L) silently drops and mislabels results on larger files — the database is fine, the query side isn't (3 bug classes, minimal repros)

**Body:**

While building a tool on top of cscope we ended up differential-testing
cscope's own `-L` queries against a direct parse of `cscope.out`. The
cross-reference database is consistently correct. The query engine is
not. Three reproducible classes on cscope 15.9, examples from
wpa_supplicant's tree:

1. **Duplicated caller attribution:** for a multi-line definition like
   `static RadiusRxResult\nradius_das_disconnect(...)`, `-L3` reports
   each call site inside it twice — once attributed to the function,
   once to the *return type*.
2. **Dropped rows:** a file with 8 call sites of one function gets 5
   reported — and the compressed vs uncompressed (`-c`) database drop
   *different* subsets.
3. **Line/file drift:** hits reported on blank lines (real site a few
   lines away), and in one case a hit attributed to a 49-line header at
   "line 1255" (the real file was the adjacent .c).

Full write-up with byte-level crossref dumps and repro commands:
<https://github.com/swchen44/ccodegraph/blob/main/docs/research/cscope-query-engine-bugs.md>
(upstream report filed).

Context, for those interested: we hit this while building **ccodegraph**,
a zero-build C code indexer (ctags + cscope crossref direct parsing +
heuristics for fn-pointer/callback dispatch, everything in one SQLite
with per-edge provenance/confidence). Since we now parse `cscope.out`
directly instead of going through `-L`, indexing an 8k-file kernel
subtree went from 3h15m to 22s, and a full Linux kernel tree (57k files)
indexes in ~62 min on a laptop — 6.2M nodes / 54.8M edges. The phantom
results above never enter the graph anymore.

Honest limitation we're chewing on: at whole-kernel scale, same-name
symbols (per-arch duplicates like `PAGE_SIZE`, per-driver statics)
explode ambiguous edges — reads alone are 28M. If you navigate large C
codebases for a living: what would you actually want from a kernel-scale
index? And how do you deal with `#ifdef`/multi-config blindness in your
current tooling (LSP/clangd sees exactly one config)?
