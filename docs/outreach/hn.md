# Hacker News 投放稿

慣例:提交連結(指向 v6 報告或 repo),作者在留言區補第一則 context
comment。HN 對「誠實負結果 + 可重現」友善,對行銷語言零容忍。
建議吸收 reddit 兩輪反饋後再發。

---

## Title 候選(擇一;HN 標題不能問句化/釣魚化)

1. `Benchmarking Claude Code's LSP against plain grep on C code: they tied (60/66 each)`
2. `We taught a coding agent to use clangd properly. It gained one point`
3. `Six rounds of benchmarking code-navigation tools for LLM agents on C codebases`

連結目標:`https://github.com/swchen44/ccodegraph/blob/main/docs/research/llm-ab-v6-lsp.md`

## 作者首則留言(context comment)

Author here. Some context on what this is and isn't.

We maintain a small zero-build C code indexer and have been benchmarking
it against alternatives for LLM-agent code navigation: 22 questions
(references, callers, `#ifdef` enumeration, include counts, call chains)
on wpa_supplicant and redis, N=3 per cell, answers graded 0-3 by a
separate model against pre-verified ground truth. This round added
Claude Code's native LSP support (clangd + a real
`compile_commands.json`).

Headline numbers (medians out of 66): plain grep 60, clangd LSP
out-of-the-box 60 (at 16% higher cost), LSP + a hand-written usage skill
61, our indexer 63.

Three findings we think generalize:

1. *Tool presence isn't tool usage.* With LSP available and the prompt
   saying "prefer LSP", 36% of runs never invoked it. A one-line "when
   to use it" hint did nothing (9-run probe). A full teaching skill
   shifted usage from scattershot symbol search to call-hierarchy ops
   (5 → 26 uses) — and bought exactly one point.
2. *Grep on C is a much stronger baseline than on TS/Java.* Headers,
   textual includes, and macros (invisible to tree-sitter and painful
   for clangd's single-config view) are grep's home turf. CircleCI
   measured the opposite result on 149K-line TypeScript — both results
   are consistent once you condition on language and task type. Our
   writeup includes that reconciliation survey.
3. *Verify your oracle.* Along the way we found cscope's `-L` query
   engine silently drops/duplicates/mislabels results on larger files
   (database is fine, query side isn't — reported upstream), and
   clangd's findReferences can return a small fraction of true
   references with no incompleteness warning. Any eval or product that
   treats tool output as ground truth inherits these silently. Our own
   grading pipeline had a version of the same bug (answer window
   truncation) — fourth time this lesson has bitten us, documented in
   the report.

Scope: C only, read-only navigation Q&A (not the edit loop where LSP
diagnostics legitimately shine), medium repos, one model family.
Everything is reproducible — harness, the clangd plugin, scoring
prompts, all 264 run/grade JSONs, REPRODUCE.md with expected numbers.

What we'd genuinely like from HN: counter-examples. If LSP-for-agents
worked clearly better for you, what was the task/language/scale?
