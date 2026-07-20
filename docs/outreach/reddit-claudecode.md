# r/ClaudeCode 投放稿(v3:三部曲版,2026-07-20)

背景:v6 靈感來自本版的「Enable LSP in Claude Code」討論串;v7/v8 把
LSP 的另兩個理論價值也測完。發文者:使用者本人。text post。

---

**Title:** We ran 3 controlled benchmarks on Claude Code's LSP support (navigation, editing, slow builds — 390 runs total). It never beat plain grep+make. Full repro packages inside.

**Body:**

A while back this sub discussed enabling LSP in Claude Code for better
code navigation. We wanted numbers, so we ran a controlled benchmark —
then two follow-ups to chase the "but LSP's real value is X" rebuttals
before anyone made them. All on C codebases (wpa_supplicant, redis)
with real `compile_commands.json`, frozen prompts, N=3, independently
judged (LLM grader for navigation, **the compiler itself** for edits).

**Round 1 — navigation Q&A** (22 questions × 3 runs, graded 0-3
against pre-verified ground truth):

| arm | score /66 | cost/point |
|---|---|---|
| plain grep/read | 60 | $0.290 |
| clangd LSP plugin (out of box) | 60 | $0.336 |
| LSP + a hand-written skill teaching it when/how to use LSP | 61 | $0.431 |
| our own code-graph indexer (disclosure: we build it) | 63 | $0.347 |

Matches this sub's #1 complaint: with the plugin working and the prompt
saying "prefer LSP", **36% of runs never called LSP once**.
`incomingCalls` — the killer feature for "who calls X" — was used 4
times in 66 runs. The popular fix (a "prefer LSP" line in CLAUDE.md):
9 probe runs, no measurable effect. A full teaching skill made usage
more *precise* (call-hierarchy ops 5→26) and bought exactly +1 point.

**Round 2 — the edit loop** ("but diagnostics shine when *writing*
code"). 8 edit tasks (signature changes, struct extraction, injected
bugs, API migration up to 37 sites across 10 files) × 4 arms × 3 runs,
judged by the compiler: build must pass, all sites must change. Arms:
grep-only / LSP with diagnostics push / **LSP with diagnostics
disabled** (isolation arm) / our indexer.

Result: **all four arms 24/24. Dead tie.** Transcripts show why: every
arm runs `make` ~3× per task — grep→Edit→make IS the agent's native
feedback loop, and incremental C builds are seconds. Millisecond
diagnostics compete against "slightly slower feedback", not "no
feedback". LSP queries nearly vanished during edits (5 calls in 96
runs): for a signature change, **the compiler's error list is
findReferences**.

**Round 3 — expensive builds** ("fine, but on big projects where make
takes minutes, diagnostics save real time"). Same tasks, but a wrapper
Makefile forces a full clean rebuild (~60s) on every make invocation,
single-target detours included, and the prompt says so.

Result: **still all-PASS, still a dead tie.** But the behavior data is
the story: agents cut make usage by **83%** (from ~3/run to ~0.5) —
they read the price and economize — yet they did NOT switch to a
cheaper verification channel (zero manual `gcc -fsyntax-only`, 2 LSP
calls, the diagnostics hook injected ~100 lines of clangd output for
exactly zero benefit). They just… stopped verifying and trusted their
edits. And they were right: correctness didn't move. At this task
difficulty, the verification loop itself is optional.

**Honest scope:** C only, medium repos, one model family (sonnet),
batch mode. Not tested: TS/Java at scale (CircleCI measured grep
genuinely *missing* references on 149K-line TypeScript — LSP won
there), real 30-minute monorepo builds, unbuildable trees, interactive
sessions where a human waits. Our writeup includes a survey reconciling
the external positive claims with these results.

Also caught along the way and filed upstream: three bug classes in
cscope's own query engine (<https://sourceforge.net/p/cscope/bugs/306/>),
and clangd's `findReferences` silently returning 4 of several hundred
true references with no warning — cross-check counts if you rely on it.

Everything is reproducible — harnesses, the clangd plugin (local
marketplace), all 390 run/grade JSONs, REPRODUCE.md with expected
numbers:
<https://github.com/swchen44/ccodegraph/blob/main/docs/research/llm-ab-v6-lsp.md>
(navigation) → `llm-ab-v7-edit-loop.md` (edits) →
`llm-ab-v8-slow-build.md` (expensive builds).

**Questions for this sub:**
1. If LSP worked clearly better for you — what task/language/repo
   size? We want counter-examples to map the boundary.
2. Has anyone measured LSP value on TS/Java monorepos with agents?
   That's the regime we haven't touched.
3. Would you trust an agent that skips verification because build is
   slow? Ours did, and got away with it — on *these* tasks.
