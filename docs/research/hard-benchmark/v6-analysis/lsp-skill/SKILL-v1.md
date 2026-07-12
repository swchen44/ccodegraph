---
name: lsp-nav
description: Invoke FIRST, before answering any C/C++ code-navigation question — complete playbook for the `LSP` tool (clangd) — which operation answers which question type, how to get coordinates cheaply, index warm-up, and the blind spots that silently corrupt answers. Use for who-calls/who-references/where-defined/what-type/impact questions in C/C++. Triggers on "誰呼叫", "who calls", "callers of", "references to", "定義在哪", "誰讀寫", "impact of".
---

# LSP (clangd) navigation playbook

One-line model: `LSP` answers **semantic questions at an exact position** —
`{operation, filePath, line, character}` (all 1-based; `workspaceSymbol`
adds `query`). It sees compiler truth (macros expanded, typedefs resolved,
same-name symbols separated) — but only for files in the compile DB.
If `LSP` is not in your tool list, load it first: ToolSearch
`query="select:LSP"`.

## Which operation for which question

| Question shape | Recipe |
|---|---|
| Where is X defined? | `workspaceSymbol(query="X")` → `goToDefinition` at the hit |
| Who calls X? | position of X's **definition** → `prepareCallHierarchy` → `incomingCalls` — returns caller names + their lines + call sites in one shot |
| What does X call? | `outgoingCalls` at the definition |
| All uses of X? | `findReferences` at the definition, then **cross-check** (see Trust) |
| Type/signature of X? | `hover` (expands typedefs) |
| What's inside this file? | `documentSymbol` — full outline with signatures |

## Getting coordinates (3-step ladder)

1. `workspaceSymbol(query="name")` — `filePath` must point at ANY real
   existing file (e.g. a file you suspect); `"."` or a bare filename that
   is not at that relative path fails with a tool error.
2. If empty: `grep -rn '\bname\b' <dir>` for file+line; column (1-based):
   `awk 'NR==<line>{print index($0,"name")}' <file>`.
3. Aim `character` INSIDE the identifier, ideally its first character.

## Index warm-up (do once, first)

Fire `documentSymbol` at one known `.c` file. Empty result = index still
loading — retry once after a short pause before concluding anything.
"No symbols found in workspace" early in a session usually means warm-up,
not absence.

## Trust calibration — blind spots (most important section)

1. **Results can be silently incomplete.** `findReferences` may return a
   fraction of the true references with NO warning (index coverage).
   Discipline for every count/enumeration answer: also grep-count
   (`grep -rn '\bX\b' … | wc -l`), reconcile the two numbers, and only
   answer once you can explain the difference (comments/strings vs code,
   out-of-DB files). If they disagree, the larger set is your search space.
2. **Single build config.** The compile DB covers ONE configuration.
   Files not compiled in it (alternative-platform implementations,
   disabled-feature files) are INVISIBLE to LSP. When a file matters,
   check whether it appears in `compile_commands.json`; if not, cover it
   with grep and say so explicitly in your answer.
3. **No LSP primitive — go straight to grep for:** "which files #include
   this header" (count BOTH spellings: `#include "x.h"` and
   `#include "dir/x.h"`); `#ifdef` enumeration (search BOTH `#ifdef X`
   and `defined(X)`); build-system gating (a config can exclude whole
   files via `Makefile`/`Kconfig` `OBJS +=` — check build files too).
4. **Same-name symbols.** LSP answers are position-scoped (precise);
   grep is name-scoped (over-broad). When grep finds more sites than LSP,
   some may belong to a different same-name symbol — verify suspicious
   sites individually with `goToDefinition`.

## Answer discipline

- Enumeration questions: list EVERY item to the end — never stop
  mid-list; count your own list and make the stated total match it.
- State method + coverage honestly: which parts came from LSP, which
  from grep, what was outside the compile DB.
- Before finalizing a load-bearing claim, Read the exact cited lines.
