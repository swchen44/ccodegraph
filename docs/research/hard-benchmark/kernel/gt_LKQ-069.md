# GT — LKQ-069 (dataflow-lifetime, L3)

**File under test:** `kernel/params.c` (Linux v6.6) — single-file scope, literal.

## Question (verbatim)

> In kernel/params.c (this file only), examine every kmalloc/kzalloc/kmalloc_array call site. For each: file:line, enclosing function, and classify the allocation's fate: (a) freed on an error path in the same function (give the kfree file:line), (b) ownership transferred (say to whom/where), or (c) freed unconditionally in the same function. Do NOT report ownership transfers as leaks.

## Question-text notes (flag)

- **`kmalloc_array` has ZERO call sites in kernel/params.c (v6.6).** The question names it, but the correct answer is "none found". An answer must not invent a kmalloc_array site; explicitly stating "no kmalloc_array" is a positive signal, silence about it is acceptable.
- **No `kmemdup`/`kstrdup` in this file either** (verified by grep). Mentioning their absence is fine; not required, never penalized.
- Two **`krealloc`** calls (lines 652, 661, in `add_sysfs_param`) are adjacent to the named family and part of the same lifetime story. Not required by the question text; mentioning them (with correct fate) must NOT be penalized — see Site notes.
- **Notable: NONE of the 4 sites is fate (a) or (c).** Every allocation in this file transfers ownership out of the allocating function. An answer that manufactures an in-function error-path kfree or an unconditional kfree for any site is misclassifying.

## Definitive site inventory: 4 sites (1 kmalloc, 3 kzalloc, 0 kmalloc_array)

| # | file:line | Allocator | Enclosing function | Fate | Freed where (eventually) |
|---|-----------|-----------|--------------------|------|--------------------------|
| 1 | kernel/params.c:51 | `kmalloc(sizeof(*p) + size, GFP_KERNEL)` | `kmalloc_parameter()` | **(b) ownership transferred** — linked into file-static list `kmalloced_params` (line 56 `list_add(&p->list, &kmalloced_params)`); `p->val` returned to caller and stored into `*(char **)kp->arg` by `param_set_charp` (line 277), a kernel_param that outlives the function | `maybe_kfree_parameter()` — `kfree(p)` at **line 71**; invoked from `param_set_charp` line 272 (frees previous value on re-set) and `param_free_charp` line 296 (the `.free` op of `param_ops_charp`, line 303, called via `destroy_params` line 759) |
| 2 | kernel/params.c:639 | `kzalloc(sizeof(*mk->mp), GFP_KERNEL)` | `add_sysfs_param()` | **(b) ownership transferred** — stored directly into `mk->mp` (the caller's `struct module_kobject`, which outlives the function). On this function's later error paths (lines 648, 657, 665) it returns -ENOMEM **without freeing** — deliberate, per in-code comment line 646: `/* Caller will cleanup via free_module_param_attrs */` | `free_module_param_attrs()` — `kfree(mk->mp)` at **line 694**; called on error by `module_param_sysfs_setup` (line 719) and after `sysfs_create_group` failure (line 731), and at teardown by `module_param_sysfs_remove` (line 748) |
| 3 | kernel/params.c:644 | `kzalloc(sizeof(mk->mp->grp.attrs[0]), GFP_KERNEL)` | `add_sysfs_param()` | **(b) ownership transferred** — stored into `mk->mp->grp.attrs`; same caller-cleanup contract as site 2 (comment line 646). If this kzalloc itself fails, function returns -ENOMEM at line 648 leaving `mk->mp` (site 2) for the caller — still not a leak | `free_module_param_attrs()` — `kfree(mk->mp->grp.attrs)` at **line 693** (guarded by `if (mk->mp)`), same call sites as site 2 |
| 4 | kernel/params.c:772 | `kzalloc(sizeof(struct module_kobject), GFP_KERNEL)` | `locate_module_kobject()` (`__init`) | **(b) ownership transferred** — to the kobject core / `module_kset`: `mk->kobj.kset = module_kset` (776), registered via `kobject_init_and_add` (777), refcount pinned by `kobject_get(&mk->kobj)` (791) so the kobject is **intentionally permanent** for built-in modules (later lookups find it via `kset_find_obj`, line 768). Never kfree'd — by design, not a leak | Never (kernel lifetime). On the `kobject_init_and_add`/`sysfs_create_file` error path, `kobject_put(&mk->kobj)` (line 784) hands the object to the kobject release path (`module_kobj_release`, line 945) |

### Site notes / grader guidance

- **Site 1** — allocation-failure path inside `kmalloc_parameter` (lines 52–53) returns NULL: nothing was allocated, nothing to free. Answers must NOT call the missing local kfree a leak; the `kmalloced_params` list + `maybe_kfree_parameter` IS the ownership mechanism. Attributing the site to `param_set_charp:277` (the wrapper's caller / where the pointer escapes) instead of `kmalloc_parameter:51` is acceptable if the mechanism is explained; the enclosing function of the literal kmalloc is `kmalloc_parameter`.
- **Sites 2–3** — the classic trap: `add_sysfs_param` returns -ENOMEM on lines 648/657/665 with **no kfree in sight**. That is NOT fate (a) and NOT a leak; the documented contract (comment at line 646, function header comment lines 623–624 "Always cleans up if there's an error" — meaning the setup path as a whole) is caller cleanup via `free_module_param_attrs` (lines 690–696). Classifying these as (a) "freed on error path in same function" is wrong (the kfree is in the CALLER); classifying as leak is wrong. Credit requires (b) with the caller-cleanup mechanism named (free_module_param_attrs and/or its call sites 719/731/748).
- **Site 2/3 realloc pattern (bonus, not required)** — `krealloc(mk->mp, ...)` line 652 and `krealloc(mk->mp->grp.attrs, ...)` line 661: on krealloc failure the ORIGINAL block is untouched and still owned by `mk->mp`/`grp.attrs`, so the caller's `free_module_param_attrs` still reclaims it; on success the (possibly moved) new pointer is re-stored (658, 666) and pointers fixed up (682–685). Mentioning this correctly is a plus; omitting it costs nothing.
- **Site 4** — `BUG_ON(!mk)` (773) on alloc failure, so no failure path to free. The struct is never kfree'd anywhere in the kernel: built-in module kobjects live forever, pinned by the extra `kobject_get` (791). Acceptable phrasings: "transferred to kobject core / module_kset", "permanent boot-time object, freed never by design". Subtle nuance (bonus only, never required, never penalized): `module_kobj_release` (945–949) does `complete(mk->kobj_completion)` and does NOT kfree the struct, so even the line-784 error path does not reclaim the memory — a known quirk of this `__init` should-never-fail path (`pr_crit` at 785). Calling site 4 a "leak" as the primary classification is WRONG; noting the error-path quirk as a caveat on top of a (b) classification is fine.
- **Fates (a) and (c): correct count is ZERO sites each.** Any answer placing a site in (a) or (c) has a misclassification.

## Evidence quotes

- L51–59 (`kmalloc_parameter`): `p = kmalloc(sizeof(*p) + size, GFP_KERNEL); ... list_add(&p->list, &kmalloced_params); ... return p->val;`
- L63–76 (`maybe_kfree_parameter`): `if (p->val == param) { list_del(&p->list); kfree(p); break; }` (kfree at L71)
- L272 / L277 (`param_set_charp`): `maybe_kfree_parameter(*(char **)kp->arg); ... *(char **)kp->arg = kmalloc_parameter(strlen(val)+1);`
- L294–297 (`param_free_charp`): `maybe_kfree_parameter(*((char **)arg));`
- L639–648 (`add_sysfs_param`): `mk->mp = kzalloc(sizeof(*mk->mp), GFP_KERNEL); ... mk->mp->grp.attrs = kzalloc(...); /* Caller will cleanup via free_module_param_attrs */ if (!mk->mp->grp.attrs) return -ENOMEM;`
- L690–696 (`free_module_param_attrs`): `if (mk->mp) kfree(mk->mp->grp.attrs); kfree(mk->mp); mk->mp = NULL;`
- L717–720 (`module_param_sysfs_setup`): `err = add_sysfs_param(...); if (err) { free_module_param_attrs(&mod->mkobj); return err; }`
- L772–791 (`locate_module_kobject`): `mk = kzalloc(sizeof(struct module_kobject), GFP_KERNEL); BUG_ON(!mk); ... err = kobject_init_and_add(&mk->kobj, &module_ktype, NULL, "%s", name); ... if (err) { kobject_put(&mk->kobj); ... return NULL; } /* So that we hold reference in both cases. */ kobject_get(&mk->kobj);`
- L945–949 (`module_kobj_release`): `complete(mk->kobj_completion);` (no kfree)

## Rubric (0–3)

- **3** — All 4 sites found (params.c:51, 639, 644, 772) with correct fate for each: all four are (b) ownership transfers, with the transfer target/mechanism correctly named per site (kmalloced_params list + maybe_kfree_parameter; mk->mp caller-cleanup via free_module_param_attrs; permanent kobject in module_kset). No site reported as a leak. Correctly reports zero kmalloc_array sites (explicitly or by simply listing no such site). Bonus mentions (krealloc pair, kmemdup/kstrdup absence, module_kobj_release quirk) neither required nor penalized.
- **2** — All 4 sites found, but exactly 1 misclassification (e.g., sites 2/3 labeled fate (a) because the kfree was attributed to the same function; or site 4's mechanism wrong while still not called a leak).
- **1** — Missed one or more of the 4 sites, OR reported any ownership transfer as a leak (e.g., "add_sysfs_param leaks mk->mp on -ENOMEM", "locate_module_kobject leaks mk"), OR 2+ misclassifications.
- **0** — Fabricated sites (e.g., a nonexistent kmalloc_array), out-of-file sites counted as in-file, or mostly wrong.

Scoring notes: do not require kmemdup/kstrdup/krealloc coverage; do not penalize their (correct) mention. Line numbers within ±2 acceptable if the function and code fragment are unambiguous. An answer flagging that the question names kmalloc_array but the file has none is correct behavior, not an error.
