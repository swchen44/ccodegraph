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

**Honest scope of the patch:** it fixes the minimal case and the common
single-line `T (*f)(args)` form. In the real wpa header there is a
*multi-line* variant where the arg-list parens open on the next line
(`RadiusRxResult (*handler)\n(struct radius_msg *msg, ...)`) which my
shape test doesn't yet catch — same root cause, harder to guard in the
regex/lexer without your scanner expertise. I'd rather send you the
localized cause and a working fix for the clean cases than a fragile
catch-all. Happy to iterate.

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

We believe classes 2 and 3 (dropped/drifted rows in radius_das.c) are
downstream of the same open-phantom-scope from radius_client.h's
`RadiusRxResult (*handler)` declaration, but we've only hard-minimized
class 1.
