# cscope #306 回覆稿(2026-07-21;回應 Hans-Bernhard Broeker)

發文者:使用者本人。貼 SourceForge 留言區。

---

Thanks for looking at this — your instinct about function pointers was
exactly the right thread to pull. We minimized the report down to a
**6-line self-contained repro** that needs nothing from wpa_supplicant,
and it also localizes the root cause. Details below, plus answers to
your three points.

## Self-contained repro (2 files, 6 lines)

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
b.c RxResult 3 probe_call();      <-- phantom caller from the OTHER file
b.c dispatch 3 probe_call();      <-- correct
```

Every call site in b.c is attributed twice: once to the correct
enclosing function, once to `RxResult` — an identifier that only occurs
in a.h, inside a function-pointer parameter declaration.

## Root cause (cscope's own view)

```
$ cscope -d -f cs.out -L1 RxResult
a.h RxResult 1 void register_handler(RxResult (*handler)(void ), void *data);
```

The scanner records the *return type* of the function-pointer parameter
as a **function definition**. That phantom "function" has no closing
brace, so its scope never ends — it stays open across the end of a.h
and swallows every subsequent file, which is why callers in unrelated
files get double-attributed to it. (Ablation: removing the fn-ptr
declaration line makes everything clean; single-line vs multi-line
formatting is irrelevant.)

So yes — it's in the function-pointer handling as you suspected, but
the observable result is a cross-file phantom *caller* whose name is a
type, which I'd argue is a bug rather than a documented limitation.

We believe classes 2 and 3 are downstream of the same
open-phantom-scope state (the dropped/duplicated rows in radius_das.c
sit exactly in the region shadowed by `RadiusRxResult` from
radius_client.h, which has the same `RadiusRxResult (*handler)(...)`
pattern at line ~239), but we've only hard-minimized class 1 so far.

## On your specific points

1. *"radius_das_disconnect unchanged for 14 years"* — agreed, and we
   never meant the source changed; the claim was about the query
   output. With the synthetic repro above the wpa tree is no longer
   needed at all.
2. *"17 call sites, not 8"* — that's the whole-tree count (it includes
   radius_client.c etc.). Our "8" is the count **within
   src/radius/radius_das.c only**; the report's claim is that querying
   the whole-tree database and filtering to that one file returns 5 of
   those 8 (compressed db) resp. a different subset (-c db).
3. *"cannot reproduce class 3"* — worth noting our platform: macOS
   arm64, cscope 15.9 built from the vanilla SourceForge tarball (the
   Homebrew formula applies no patches). If you're on Linux this may
   be platform-sensitive; the 6-line repro above reproduces class 1
   deterministically here and should be a better cross-platform test
   than the tree-dependent cases.

Happy to run any diagnostics you'd find useful.
