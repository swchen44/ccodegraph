# GT WRQ-001: definition of eloop_register_timeout()

Repo: wpa_supplicant (real checkout at
`/Users/swchen.tw/git/cbm-vs-codegraph-bench/repos/wpa_supplicant`)

## Question (verbatim)

"Find the definition of eloop_register_timeout(). Return file, line, and full
signature."

No scope-limiting phrase in the question (contrast with WRQ-013's "across the
whole src/ tree"), so no directory restriction applies here.

## Method

Not grep-guessed: read the actual source at the matched lines to confirm each
is a full function body (definition) vs. a bare prototype (declaration), then
checked the build system (`wpa_supplicant/Makefile`, `nmake.mak`, VS2005
project file, `defconfig`) for whether more than one translation unit could
supply this symbol — the category of trap the task brief warns about (a whole
file/definition gated by the build system, invisible to plain source grep).

```
grep -n "eloop_register_timeout" src/utils/eloop.h src/utils/eloop.c src/utils/eloop_win.c
```

## Definitive answer

**Primary / canonical definition** (the one any default Linux/BSD/macOS build
uses, and the one implied by "the" definition absent further qualification):

- **File:** `src/utils/eloop.c`
- **Line:** 601
- **Full signature:**
  ```c
  int eloop_register_timeout(unsigned int secs, unsigned int usecs,
  			   eloop_timeout_handler handler,
  			   void *eloop_data, void *user_data)
  ```
  (verified as a real function body — `os_zalloc`, timeout-list insertion
  logic etc. follow immediately, lines 601-~680s — not a prototype)

**Declaration only (must NOT be given as the answer):**

- `src/utils/eloop.h:179` —
  `int eloop_register_timeout(unsigned int secs, unsigned int usecs, eloop_timeout_handler handler, void *eloop_data, void *user_data);`
  This is a semicolon-terminated prototype inside a Doxygen-style comment
  block (`eloop.h:167-181`), not a definition. The draft evaluation_notes'
  claim "must be eloop.c, not eloop.h" is **confirmed correct** by direct
  source inspection.

### Build-system-level second definition (verified, not a source-grep artifact)

There is a **second, real function body** with the exact same name and
signature at `src/utils/eloop_win.c:237`:

```c
int eloop_register_timeout(unsigned int secs, unsigned int usecs,
			   eloop_timeout_handler handler,
			   void *eloop_data, void *user_data)
```

This is wpa_supplicant's alternate Windows-native event loop implementation.
It is selected instead of `eloop.c` only when the build is configured for
native Windows:

- `wpa_supplicant/Makefile:128-131`: `CONFIG_ELOOP` defaults to `eloop`
  (→ `../src/utils/eloop.o`) unless overridden; `defconfig:262-264` documents
  `CONFIG_ELOOP=eloop_win` as the explicit opt-in for "Windows events and
  WaitForMultipleObject() loop".
- `wpa_supplicant/nmake.mak:64` (the native Windows nmake build) hardcodes
  `$(OBJDIR)\eloop_win.obj`, i.e. `eloop.c` is never compiled in that build at
  all.
- `wpa_supplicant/vs2005/wpa_supplicant/wpa_supplicant.vcproj:334` directly
  references `..\..\..\src\utils\eloop_win.c` as the compiled source.
- `wpa_supplicant/ChangeLog:1453` documents `CONFIG_ELOOP=eloop_win in
  .config` as a historical real option.

So exactly like the sae.c Makefile whole-file gate found earlier in this
benchmark round, `eloop_register_timeout()` genuinely has two build-selected
definitions in this repo — but unlike that case, the question asks for "the"
definition with no tree-wide scope, and `eloop.c` is unambiguously the
default/canonical one (used by the ordinary `make`, Linux/BSD/macOS/Android
builds; `eloop_win.c` is compiled only under the Windows-specific nmake/MSVC
project files which don't even use the shared `Makefile`). Treat `eloop.c:601`
as the required answer; mentioning `eloop_win.c:237` as a Windows-only
alternate is a bonus, not a requirement, and is not itself a scope violation
since the question has no directory-restricting clause to violate.

## Scoring rubric (0-3)

- **Score 3**: Names `src/utils/eloop.c`, line 601 (±1-2 lines is fine —
  e.g. citing the line of the `int eloop_register_timeout(` token vs. the
  brace), and reproduces the full 5-parameter signature (`unsigned int secs,
  unsigned int usecs, eloop_timeout_handler handler, void *eloop_data, void
  *user_data`) returning `int`. Optionally, and without penalty either way,
  may note the `eloop_win.c:237` Windows-build alternate.
- **Score 2**: Correct file (`eloop.c`) and correct general signature, but
  line number is substantially wrong (e.g. off by tens/hundreds of lines,
  suggesting no real read of the file), OR the signature is truncated/missing
  a parameter, OR the answer conflates the two valid definitions in a
  confusing way (e.g. reports `eloop_win.c` as *the* answer instead of the
  default one) without acknowledging eloop.c as canonical.
- **Score 1**: Answer is `src/utils/eloop.h:179` (the declaration) presented
  as if it were the definition — this is exactly the declaration-vs-definition
  trap the question is designed to catch — or the function body/signature is
  wrong (wrong parameter types/count, wrong return type).
- **Score 0**: Wrong symbol entirely, or a hallucinated file/line with no
  correspondence to the actual repo content.
