# r/ClaudeCode 投放稿

背景:v6 的靈感就來自這個版的「Enable LSP in Claude Code」討論串。
這篇直接回應社群自己的話題,並量化了他們的頭號抱怨。

---

**Title:** We benchmarked the clangd LSP plugin against plain grep on C codebases: 22 questions × 3 runs each, independently graded. They tied. Full repro package inside.

**Body:**

A while back this sub discussed enabling LSP in Claude Code for better
code navigation. We wanted numbers, so we ran a controlled benchmark on
two C repos (wpa_supplicant, redis) with real `compile_commands.json`:

**Setup:** 22 code-navigation questions (find definitions, all
references, callers, `#ifdef` enumeration, include counting, call-chain
tracing…), 3 arms × 22 × 3 reps = 198 headless runs (plus a 66-run
follow-up arm), same model (sonnet), same frozen prompts, scored 0-3 by
a separate model against pre-verified ground truth.

**Results (median totals out of 66):**

| arm | score | cost/point |
|---|---|---|
| plain grep/read | 60 | $0.290 |
| clangd LSP plugin (out of box) | 60 | $0.336 |
| LSP + a hand-written skill teaching it *when/how* to use LSP (follow-up) | 61 | $0.431 |
| our own code-graph indexer (disclosure: we build it) | 63 | $0.347 |

Full disclosure: we maintain that last tool, so we have a horse in this
race — which is exactly why every prompt, run JSON, grade JSON and a
step-by-step REPRODUCE.md are public. The LSP findings stand on their
own regardless of our arm.

**The most interesting part matches this sub's #1 complaint:** even with
the plugin working and the prompt saying "prefer the LSP tool", **36% of
LSP-arm runs never called LSP once** (342 Bash calls vs 117 LSP calls
overall). `incomingCalls` — the killer feature for "who calls X" — got
used 4 times in 66 runs. We also tested the popular fix of adding a
"prefer LSP" instruction: 9 probe runs, basically no effect on usage.
A full teaching skill made usage more *precise* (call-hierarchy ops went
5 → 26) but not more frequent, and it bought exactly +1 point.

**Caveats, honestly:** this is C (grep's best language — headers,
textual `#include`s, macros), read-only navigation Q&A (not the edit
loop where LSP diagnostics shine), medium-size repos, one model. On
149K-line TypeScript, CircleCI measured the opposite (grep genuinely
missed references). Our writeup includes a survey reconciling both:
in short, LSP's real home turf is the *edit* loop (post-edit
diagnostics), not navigation Q&A on C.

Also caught along the way: clangd's `findReferences` can silently
return a fraction of the true references with no warning (we have a
case of 4 returned out of hundreds), so cross-check counts if you rely
on it. (Same oracle-trust lesson bit us with cscope's query engine —
three bug classes, filed upstream with minimal repros:
<https://sourceforge.net/p/cscope/bugs/306/>.)

Everything is reproducible: harness, the clangd plugin (local
marketplace), scoring prompts, raw run/grade JSONs, and a step-by-step
REPRODUCE.md:
<https://github.com/swchen44/ccodegraph/blob/main/docs/research/llm-ab-v6-lsp.md>

**Questions for this sub:**
1. If LSP worked great for you — what task/language/repo size? We want
   counter-examples to map the boundary.
2. Has anyone gotten Claude to *consistently* prefer LSP tools? What did
   it take?
3. For C folks: how do you handle `#ifdef`/multi-config navigation today?
