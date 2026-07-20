# cscope #306 回覆稿(2026-07-21;含 patch)

發文者:使用者本人。貼 SourceForge 留言區。附件:cscope-306-fscanner.patch。

---

Thanks — your function-pointer instinct was exactly right, so we chased
it into the scanner and have a **root cause, a 6-line repro, and a
candidate patch**.

## 6-line self-contained repro (no wpa_supplicant needed)

```c
/* a.h */
void register_handler(RxResult (*handler)(void), void *data);
```
```c
/* b.c */
static int dispatch(void)
{
	probe_call();
	return 0;
}
```
```
$ cscope -bk a.h b.c -f cs.out
$ cscope -d -f cs.out -L3 probe_call
b.c RxResult 3 probe_call();      <-- phantom caller, from a DIFFERENT file
b.c dispatch 3 probe_call();      <-- correct
```

## Root cause (fscanner.l)

`cscope -d -f cs.out -L1 RxResult` shows it: the lexer records the
return type of a function-pointer parameter as a **function
definition**. In the `<WAS_IDENTIFIER>` rule, a declarator of shape
`T (*f)(args)` matches the "a function definition" pattern — the
identifier `T` is followed by `(`, and the `if (braces == 0 ...)` test
passes. That phantom function has no body, so `fcndef`/`braces` leave
its scope open; it then swallows the FCNCALL attribution of every
subsequent file, producing the cross-file duplicate callers.

This is precisely the case the `FIXME HBB 20001003` comment right above
that rule anticipated ("the parsing bug concerning function pointer
usage").

## Candidate patch (attached: cscope-306-fscanner.patch)

Adds a shape guard in that rule: if the text after the identifier is
`( * ... ) (` — i.e. a function-pointer declarator — treat it as a
function *call/use*, not a definition (`goto fcncal`). Verified:

- the 6-line repro is fully clean after the patch (no phantom `RxResult`
  definition, no duplicate caller, `-L1 RxResult` empty);
- no regression on ordinary defs: `int f(int a){...}` and its calls are
  still detected; a genuine fn-ptr-*returning* definition
  `int (*g(int x))(void){...}` is unaffected.

**Verified on the real wpa tree (stock vs patched):** all three
originally-reported classes trace to this one phantom scope and are
resolved by the single patch —

| symptom | stock | patched |
|---|---|---|
| duplicate `RadiusRxResult` caller on radius_das.c sites | 5 | 0 |
| correct sites returned (of 8) | 5/8 | 8/8 |
| phantom `fst_group_get_id` → `fst_internal.h:1255` (49-line file) | present | gone |
| `$RadiusRxResult` phantom marks in the crossref | 2 | 0 |

The multi-line form in radius_client.h (`RadiusRxResult (*handler)`
with the arg parens on the next line) is covered too — regress-306.sh
includes it as case 1b.

## Your three points

1. *radius_das_disconnect unchanged* — agreed; we never claimed the
   source changed, only the query output, and the repro above removes
   the tree dependency entirely.
2. *17 vs 8* — 17 is the whole-tree count; our 8 was the in-file count
   for src/radius/radius_das.c. Same numbers, different scope.
3. *cannot reproduce class 3* — our platform is macOS/arm64, cscope
   15.9 from the vanilla SourceForge tarball (Homebrew applies no
   patches). The 6-line repro above should be deterministic
   cross-platform; if it isn't for you, that itself is useful data.

Classes 2 and 3 (dropped/drifted rows in radius_das.c) turned out to be
downstream of exactly this same phantom scope — the table above shows
them clearing together with class 1 under the one patch, which we take
as confirmation of the shared root cause.

## Regression harness

Since 15.9 ships no test suite (`make check` is a no-op), the patch
comes with a small standalone regression script (attached:
regress-306.sh) covering three cases: the bug (fn-ptr param must not
create a phantom def), an ordinary function def+call must still be
detected, and a genuine fn-ptr-*returning* definition must still be a
def. Against stock 15.9 it reports case 1 FAIL; against the patched
build, ALL PASS. Usage: `./regress-306.sh /path/to/cscope`.
