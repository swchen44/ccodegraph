# GT LKQ-006: definition of `container_of` used by kernel code (+ disambiguation of all other copies)

**Category**: symbol-definition | **Difficulty**: L2 | **Kernel**: v6.6 (`ffc253263` "Linux 6.6") | **Repo**: `repos/linux-v6.6` (shallow clone, single commit)

## Question (verbatim)

> Find the definition of the container_of macro that kernel code actually uses (not copies
> under tools/ or scripts/). Return the file path and line number, quote the full macro body,
> and explain its three parameters. Also report whether OTHER definitions of container_of
> exist elsewhere in the tree (e.g. under tools/) and why they do not conflict with the
> kernel one.

Question-text check: **accurate, no flag needed.** The primary definition is where the
question implies, and other copies do exist. One subtlety the question's "tools/ or scripts/"
phrasing under-covers: two additional non-kernel copies live under `drivers/` (a host
program) and `samples/` (a userspace sample). They are still not kernel code — the exclusion
should be read as "non-kernel build domains" — and an answer that finds them deserves extra
credit, not a penalty.

## Method (two independent enumerations, results identical)

1. `grep -rn "#define container_of" --include="*.h" --include="*.c"` over the whole tree.
2. `git grep -nE '^[[:space:]]*#[[:space:]]*define[[:space:]]+container_of[( ]'` over **all**
   tracked files (no extension filter; tolerant of `# define` spacing and `container_of (`).

Both methods yield exactly **10** definitions of the macro named `container_of` (list below).
Additionally verified: `include/linux/kernel.h:21` does `#include <linux/container_of.h>`
(the kernel.h relationship), and `drivers/gpu/drm/radeon/Makefile:6` declares
`hostprogs := mkregtable` (proving the drivers/ copy is a host tool, not kernel code).
`git grep container_of -- rust/` is empty — v6.6 has **no** Rust `container_of!` macro
(that arrived in later kernels), so nothing on the Rust side to report.

## Definitive answer

### Primary definition (the one kernel code actually uses)

**`include/linux/container_of.h`, line 18** (macro body spans lines 18-23).

Full macro body, verbatim:

```c
#define container_of(ptr, type, member) ({				\
	void *__mptr = (void *)(ptr);					\
	static_assert(__same_type(*(ptr), ((type *)0)->member) ||	\
		      __same_type(*(ptr), void),			\
		      "pointer type mismatch in container_of()");	\
	((type *)(__mptr - offsetof(type, member))); })
```

The kernel-doc comment directly above it (lines 10-17) documents the parameters and warns:
"WARNING: any const qualifier of @ptr is lost." (The const-preserving companion
`container_of_const` is defined in the same file at line 32 using `_Generic`.)

### The three parameters

| Parameter | Meaning |
|---|---|
| `ptr` | A pointer to the **member** field inside some instance of the containing struct (e.g. the `struct list_head *` you got from a list iteration). It is cast to `void *` (`__mptr`) so byte arithmetic can be done on it; any `const` qualifier is dropped. |
| `type` | The **type of the containing (outer) structure** the member is embedded in (e.g. `struct my_device`). Used both for `offsetof()` and as the type of the returned pointer. |
| `member` | The **name of the field** within `type` that `ptr` points at (e.g. `list`). `offsetof(type, member)` gives its byte offset from the start of the struct. |

Mechanism: subtract the member's byte offset from the member pointer to recover the address
of the enclosing struct: `(type *)(__mptr - offsetof(type, member))`. The `static_assert`
(using `__same_type`, i.e. `__builtin_types_compatible_p`) enforces at compile time that
`*(ptr)` really has the member's type (or is `void`), catching passing the wrong pointer or
naming the wrong member.

### kernel.h relationship

`include/linux/kernel.h:21` is `#include <linux/container_of.h>`, so kernel code that only
includes `<linux/kernel.h>` (the historical home of the macro) still gets `container_of`
transitively. kernel.h does **not** define it — the definition was split out of kernel.h
into its own header in v5.16 (commit `d2a8ebbf8192`, "kernel.h: split out container_of()
and typeof_member() macros"; historical context — not verifiable from this shallow
single-commit clone). Answers naming kernel.h as the *definition site* are wrong for v6.6;
naming it as a re-export/include path is correct.

### Exhaustive list of ALL other `#define container_of` in the tree (9 sites)

All are outside the kernel-image build; C macros only "conflict" if two definitions are
visible in the same translation unit, and none of these TUs ever include
`include/linux/container_of.h`.

| # | File:Line | What it is | Why no conflict |
|---|---|---|---|
| 1 | `tools/include/linux/kernel.h:35` | tools/ mirror header used by perf, objtool, etc. (classic pre-5.16 body, no static_assert) | Userspace build domain with its own `-Itools/include`; additionally wrapped in `#ifndef container_of` |
| 2 | `tools/include/nolibc/types.h:232` | nolibc runtime for standalone test binaries (params named `PTR, TYPE, FIELD`) | Userspace/nolibc build domain; wrapped in `#ifndef container_of` |
| 3 | `tools/lib/bpf/bpf_helpers.h:90` | libbpf helper for BPF programs (no type-check, uses libbpf's own `offsetof`) | Compiled by clang for the BPF target, never with kernel headers; deliberately does `#undef container_of` first (bpf_helpers.h:89) so it wins even if another copy was in scope |
| 4 | `tools/tracing/rtla/src/utils.h:13` | rtla (realtime analysis tool) userspace copy | Standalone userspace tool build |
| 5 | `tools/usb/usbip/libsrc/list.h:133` | usbip userspace library copy | Standalone userspace (autotools) build |
| 6 | `scripts/kconfig/list.h:19` | kconfig host program's list implementation | Built with HOSTCC for the build machine; never includes kernel headers |
| 7 | `scripts/mod/list.h:18` | modpost host program's copy (notably a modern body **with** `_Static_assert`, mirroring the kernel one) | Built with HOSTCC; separate host build domain |
| 8 | `drivers/gpu/drm/radeon/mkregtable.c:28` | **Trap: under drivers/ but NOT kernel code** — a host program (`hostprogs := mkregtable`, `drivers/gpu/drm/radeon/Makefile:6`) that generates `*_reg_safe.h` at build time | Compiled with HOSTCC against system headers, not kernel headers |
| 9 | `samples/bpf/test_lru_dist.c:27` | Userspace sample/test program | Userspace TU with its own local `offsetof`/`container_of`; never includes the kernel header |

Per the prior-round lesson: every one of these 9 is a **real** definition an agent should be
credited for reporting as existing — the error mode is presenting one of them as *the*
kernel definition.

### Near-miss variants (different macro NAMES — must not be counted as `container_of` definitions)

- `container_of_const` — `include/linux/container_of.h:32` (const-preserving kernel variant)
- `container_of_user` — `drivers/gpu/drm/i915/i915_utils.h:165`
- `container_of_or_null` — `drivers/md/bcache/util.h:445`
- `container_of_dwork_rsl` — `drivers/staging/rtl8192e/rtllib.h:66`

An answer listing these as "other container_of definitions" conflates distinct symbols;
mentioning them as related variants is fine.

## Scoring rubric (0-3)

- **3** — Primary definition correctly located at `include/linux/container_of.h:18` with the
  macro body quoted accurately (must include the `static_assert` type-check and the
  `offsetof` subtraction — quoting a pre-5.16 body from memory is a body error); all three
  parameters explained correctly; AND acknowledges that other copies exist elsewhere
  (minimum: tools/ and scripts/, with the correct no-conflict rationale — separate build
  domains / host vs kernel compilation / macros are per-translation-unit). Full marks do
  not require all 9 sites, but exhaustive enumeration (especially catching
  `drivers/gpu/drm/radeon/mkregtable.c` as a hostprog and `samples/bpf/test_lru_dist.c`)
  and the kernel.h `#include` relationship distinguish a strong 3.
- **2** — Correct primary file+line and substantially correct body/parameters, but the
  other-definitions part is thin (e.g. "copies exist under tools/" with no paths or no
  conflict reasoning), or parameter explanation has a minor error, or wrongly claims
  kernel.h still defines the macro while also giving the right primary site.
- **1** — Right file but materially wrong body/line; or names `include/linux/kernel.h` as
  the definition site (include ≠ define); or lists copies but leaves ambiguous which one is
  authoritative; or counts the `container_of_const`/`_user`/`_or_null` variants as
  `container_of` definitions while otherwise mostly correct.
- **0** — Reports a tools/, scripts/, drivers/mkregtable, or samples/ copy as THE kernel
  definition; wrong file entirely; or denies that other definitions exist.

Scoring note (prior-round lesson): reporting the existence of same-name definitions in
vendored/tools directories is a verified fact — credit it. Only *misattributing* one of
them as the kernel's definition is penalized.
