# lobste.rs 投放稿

慣例:link 提交 + tags;lobste.rs 重方法論、反行銷,可比 HN 更技術。
建議 tags:`ai`, `c`, `testing`(或 `practices`)。

---

**Title:** Benchmarking LLM-agent code navigation on C: grep vs. clangd LSP vs. a code-graph indexer, N=3, independently graded

**URL:** `https://github.com/swchen44/ccodegraph/blob/main/docs/research/llm-ab-v6-lsp.md`

## 作者留言(提交後補)

This is round six of a benchmark series we run against our own tool, so
the usual caveat applies: we have a horse in this race. Mitigations:
frozen prompts published verbatim, N=3 with medians, grading by a
separate model against pre-verified ground truth, every raw run/grade
JSON in the repo, and a REPRODUCE.md that gets you from `git clone` to
our exact numbers (including the clangd plugin config and the real
compile_commands.json files).

Why lobste.rs might find this interesting beyond the headline tie
(grep 60 = LSP 60, our indexer 63, all out of 66):

- **Methodology forensics.** The series has now hit four distinct ways
  a grading pipeline silently lies to you: wrong ground truth; a grader
  trusting wrong ground truth; the grader's *view* of the ground truth
  being truncated; and this round, the grader's view of the *answer*
  being truncated (a complete 96-item answer scored as "stops partway").
  Every occurrence is documented with the re-scored deltas.
- **Verify your oracle.** Differential-testing our crossref parser
  against cscope's own `-L` queries exposed three bug classes in
  cscope's query engine (dropped rows, duplicated caller attributions,
  line-number drift) — the database is correct, the query side isn't.
  Reported upstream with minimal repros. Separately, clangd's
  findReferences returned 4 of several hundred true references with no
  incompleteness warning.
- **Tool presence ≠ tool usage.** 36% of LSP-arm runs never touched the
  LSP tool despite explicit instructions; a one-sentence "prefer LSP"
  hint did nothing measurable; a full teaching document made usage more
  precise (call-hierarchy ops 5→26) and bought exactly +1 point. The
  agent's tool prior is grep-first, and that's a training-distribution
  fact, not a prompt bug.

Scope limits are stated in the report (C, read-only navigation, medium
repos, one model). The reconciliation with opposite results on
TypeScript at 149K lines is in `lsp-external-evidence.md` in the same
repo.
