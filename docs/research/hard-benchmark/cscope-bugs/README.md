# cscope #306 — repro, root cause, patch, regression

Files here:
- `a.h`, `b.c` — the canonical 6-line reproducer
- `cscope-306-fscanner.patch` — the fix (against pristine cscope 15.9)
- `regress-306.sh` — standalone regression harness (15.9 ships no tests)

## The bug in one screen

```c
/* a.h */
void register_handler(RxResult (*handler)(void), void *data);
/* b.c */
static int dispatch(void)
{
	probe_call();
	return 0;
}
```

```
$ cscope -bk a.h b.c -f cs.out && cscope -d -f cs.out -L3 probe_call
b.c RxResult  3 probe_call();    # STOCK 15.9: phantom caller (a TYPE, from a.h)
b.c dispatch  3 probe_call();    # correct
```
```
# after the patch:
b.c dispatch  3 probe_call();    # only the correct caller
```

## Where the repro was minimized from

Original report used wpa_supplicant's `src/radius/radius_das.c` (the
`radius_msg_get_attr_ptr` call sites, double-attributed to
`RadiusRxResult`). Minimization chain:

1. **File-set ddmin** over the full 620-file wpa tree → the pair
   {`src/radius/radius_das.c`, `src/radius/radius_client.h`}. The
   header is the source: it declares
   `RadiusRxResult (*handler)(...)` (a function-pointer parameter).
2. **Line-level ddmin** on the pair → the trigger reduces to the
   fn-ptr parameter declaration in the header + any call in a second
   file.
3. **Hand reconstruction + ablation** → the header collapses to one
   line (`a.h`); ablation confirms the fn-ptr declarator is the sole
   necessary element (single-line vs multi-line formatting is
   irrelevant; removing the declarator makes everything clean).

`a.h` corresponds to the `RadiusRxResult (*handler)` shape in
`radius_client.h:239`; `b.c` stands in for any file whose callers get
swallowed by the leaked phantom scope.

## Root cause

`cscope -d -f cs.out -L1 RxResult` on stock shows the lexer recorded
`RxResult` (the fn-ptr's return TYPE) as a **function definition** with
no body — its scope never closes and leaks across files, double-
attributing every subsequent caller. This is the case the
`FIXME HBB 20001003` comment in `fscanner.l` anticipated.

## Scope of the fix (verified on the real wpa tree, stock vs patched)

| symptom | stock | patched |
|---|---|---|
| duplicate `RadiusRxResult` caller on radius_das.c sites | 5 | **0** |
| correct sites returned (of 8) | 5/8 | **8/8** |
| phantom file-drift `fst_group_get_id` → `fst_internal.h:1255` | present | **gone** |
| `$RadiusRxResult` phantom marks in crossref | 2 (−c db) | **0** |

All three originally-reported classes trace to the same phantom scope
and are resolved by the single patch. Ordinary function defs/calls and
genuine fn-ptr-*returning* definitions are unaffected (see regress-306.sh).
