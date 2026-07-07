# GT WRQ-011: struct dl_list + functions/macros that operate on it

**Category**: data-structure | **Difficulty**: L2 | **Repo**: wpa_supplicant (checkout: `515eb37`, "init from wpa_supplicant-2.5", 2016-06-30)

## Question (verbatim)

> Find the definition of struct dl_list in src/utils/list.h and list every function in
> src/utils/list.c that operates on it (insert/remove/iterate).

## CRITICAL FINDING: the question's premise is factually wrong for this repo — `src/utils/list.c` does not exist

Verified exhaustively, not assumed:

```
$ ls src/utils/ | grep -i list
list.h                              # only file; no list.c
$ find . -name "list.c"             # whole-repo search
(no output)
$ git log --all --oneline -- src/utils/list.c
(no output — no commit in this repo's history has ever added/removed this file)
$ grep -rn "list\.c\b" --include="Makefile*" .   # any build rule referencing it
(no output)
```

This is not a build-system-level exclusion (no `#ifdef`/Makefile conditional hides a
`list.c` — the file simply was never created, in this checkout or any prior commit of
it). This matches the real, long-standing upstream fact about wpa_supplicant/hostapd:
`dl_list` has always been implemented entirely as `static inline` functions and macros
in the header, with no corresponding `.c` translation unit, no `list.o` build target,
and nothing to strip out at any config level. So the literal question — "list every
function in src/utils/list.c" — has an empty/void answer as asked: **there is no such
file, hence zero functions defined there.**

The evaluation-judgment call (must be explicit in grading, per the task's warning about
scope limiters): the question's intent is clearly "list the operations that
insert/remove/iterate over `dl_list`", and a good answer should recognize the premise
error and redirect to where those operations actually live — `src/utils/list.h` itself —
rather than either (a) silently fabricating a plausible-looking `list.c` with invented
line numbers, or (b) stopping at "no such file, no answer possible" without following
through to the header. Both (a) and (b) are the two failure modes this GT scores against.

## struct dl_list definition

`src/utils/list.h:15-18`:

```c
struct dl_list {
	struct dl_list *next;
	struct dl_list *prev;
};
```

Fields: `next` (`struct dl_list *`), `prev` (`struct dl_list *`) — a classic circular
doubly-linked list node/sentinel (same struct is used as both the list head and the
embedded link field in container structs; there is no separate "head" type). Doc
comment at line 12-14: `/** struct dl_list - Doubly-linked list */`.

## Complete list of operations — ALL in src/utils/list.h, none in a .c file

Since `list.c` does not exist, "every function... that operates on it" must be answered
from `list.h`. Two kinds live there: `static inline` **functions** (real functions,
take `struct dl_list *` parameters, appear in the symbol table) and preprocessor
**macros** (textual expansion, no function symbol, but still the actual insert/remove/
iterate/accessor API surface programmers use).

### static inline functions (6 total) — these are the literal "functions" the question asks for

| # | Signature | Lines | Operation kind |
|---|-----------|-------|-----------------|
| 1 | `void dl_list_init(struct dl_list *list)` | 22-26 | init — makes `list` a self-referencing empty circular list |
| 2 | `void dl_list_add(struct dl_list *list, struct dl_list *item)` | 28-34 | **insert** — inserts `item` right after `list` (head-insert) |
| 3 | `void dl_list_add_tail(struct dl_list *list, struct dl_list *item)` | 36-39 | **insert** — inserts `item` at the tail (implemented by calling `dl_list_add(list->prev, item)`) |
| 4 | `void dl_list_del(struct dl_list *item)` | 41-47 | **remove** — unlinks `item` from its list, nulls its own `next`/`prev` |
| 5 | `int dl_list_empty(struct dl_list *list)` | 49-52 | query — `list->next == list` |
| 6 | `unsigned int dl_list_len(struct dl_list *list)` | 54-61 | **iterate** — walks the list counting nodes (internally a manual `for` loop over `->next`) |

This set matches the draft evaluation_notes' hint (`dl_list_add, dl_list_add_tail,
dl_list_del, dl_list_len`) plus `dl_list_init` and `dl_list_empty`, which the draft
omitted — confirmed as the complete function-level set by reading the whole header
top to bottom; there is nothing else taking `struct dl_list *` as a function (vs.
macro) in this file.

### macros that also take part in insert/remove/iterate/access (must be mentioned — see judgment call above)

| Macro | Lines | Role |
|-------|-------|------|
| `DL_LIST_HEAD_INIT(l)` | 20 | static initializer, e.g. for a file-scope list variable |
| `dl_list_entry(item, type, member)` | 67-68 | container-of-style cast from a `struct dl_list *` link back to the enclosing struct |
| `dl_list_first(list, type, member)` | 70-72 | **accessor** — first element or NULL if empty (uses `dl_list_empty` + `dl_list_entry`) |
| `dl_list_last(list, type, member)` | 74-76 | **accessor** — last element or NULL if empty |
| `dl_list_for_each(item, list, type, member)` | 78-81 | **iterate** — forward `for`-loop expansion, the primary iteration idiom used throughout wpa_supplicant |
| `dl_list_for_each_safe(item, n, list, type, member)` | 83-87 | **iterate** — forward, deletion-safe (caches next pointer) |
| `dl_list_for_each_reverse(item, list, type, member)` | 89-92 | **iterate** — backward `for`-loop expansion |
| `DEFINE_DL_LIST(name)` | 94-95 | declares + statically initializes a new named `struct dl_list` |

`dl_list_first`/`dl_list_last` are exactly the "first/last" the draft evaluation_notes
alluded to — but they are macros, not functions, and (like all the macros above) are
**not** in `list.c` either (there is no `list.c`) — they are also in `list.h`, right
below the inline functions.

### Sanity check that these are actually used this way elsewhere in the tree

`grep -rn "dl_list_add\b" src/utils/` (outside list.h itself) shows real call sites in
`trace.c:353`, `os_unix.c:688`, `eloop.c:642`, `eloop_win.c:275`, `edit.c:195,209` —
confirming these are live, used APIs, not dead code, even though they live entirely in
the header.

## Scoring rubric (0-3)

- **3**: Correctly gives the struct definition (fields `next`/`prev`, `list.h:15-18`),
  explicitly notes that `src/utils/list.c` does not exist in this repo (so the literal
  question has no file to enumerate from), AND redirects to `list.h` to give a complete
  or near-complete answer covering the 6 inline functions (`dl_list_init`, `dl_list_add`,
  `dl_list_add_tail`, `dl_list_del`, `dl_list_empty`, `dl_list_len`) and at least the
  macro iteration helpers (`dl_list_for_each` family) and `dl_list_first`/`dl_list_last`.
- **2**: Gets the struct right and correctly lists the real operations (functions and/or
  macros) from `list.h`, but does NOT explicitly flag that `list.c` is missing/nonexistent
  (implicitly treats list.h content as if it were "from list.c", or just silently
  ignores the file-path discrepancy) — content is right, the premise-check is missing.
  Also **2** if it flags the missing file correctly but the resulting function/macro
  list omits 1-2 items (e.g. misses `dl_list_init` or `dl_list_empty` or the `_safe`/
  `_reverse` variants).
  Also **2** if it discusses the file-existence discrepancy but its function enumeration is otherwise incomplete (missing 2+ items).
- **1**: Fabricates a plausible-looking but non-existent `list.c` (invented line numbers
  or a function body/list not actually present anywhere in the repo), OR gives only a
  partial function list (e.g. just the 4 from the draft evaluation_notes hint) without
  noting anything is missing, OR gets the struct definition wrong in a minor way (e.g.
  wrong line number but right fields).
- **0**: Wrong struct fields, or wrong file entirely, or a materially wrong/hallucinated
  set of "functions in list.c" presented with confidence and no acknowledgment that
  list.c doesn't exist, or no attempt made.

## Note on why this matters for grading agent answers

This question is structurally similar to WRQ-020 (the "does eloop.c use locks" trap,
correct answer "not applicable — single-threaded") in that a naive agent that trusts
the question's file path at face value and either (a) hallucinates `list.c` content to
match the expected shape of the answer, or (b) gives up entirely without checking the
header, both fail the actual test of code-navigation competence: correctly locating
where the real implementation lives when the question's own premise about file
location is subtly wrong.
