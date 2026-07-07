# GT WRQ-018 (category: dataflow-lifetime, difficulty: L3)

## Question (verbatim)

"Find every os_malloc() call in src/utils/os_unix.c's callers within
src/eap_common/ and confirm each has a matching os_free() on all exit paths
(including error paths)."

## Clarified scope

The phrasing is ambiguous but resolves to one reading once you look at what
`src/utils/os_unix.c` actually contains:

- `os_unix.c:677` **defines** `os_malloc()` itself — a thin wrapper around
  libc `malloc()` plus allocation-tracing bookkeeping
  (`struct os_alloc_trace`, `dl_list_add(&alloc_list, ...)`,
  `wpa_trace_record`). It is the allocator, not a caller of it.
- `os_unix.c` does contain 3 other `os_malloc(...)` call sites of its own
  (lines 288, 309, 417 — inside `os_unix.c`'s own helpers such as
  `os_rel2abs_path`), but those are `os_unix.c` calling its own allocator
  internally, not something happening "within src/eap_common/".

So "os_malloc() call in os_unix.c's callers within src/eap_common/" cannot
mean "malloc calls inside os_unix.c" — it means: **functions defined in
`src/eap_common/*.c` that call `os_malloc()`** (the allocator that
`os_unix.c` implements). This is the reading used below: every
`os_malloc(` call site in `src/eap_common/*.c`, with its enclosing function
read in full (all branches, all `goto`/cleanup labels) to check `os_free()`
coverage on every exit path.

Scope note: `src/eap_common/*.c` only (9 files with matches out of the
~19 `.c` files in the directory: `eap_eke_common.c`, `eap_fast_common.c`,
`eap_gpsk_common.c`, `eap_ikev2_common.c`, `eap_pwd_common.c`,
`eap_sake_common.c`, `eap_sim_common.c`, `ikev2_common.c`). No `.h` file in
`src/eap_common/` contains an `os_malloc(` call. Total: **26 call sites**.

## Method

`grep -n "os_malloc(" src/eap_common/*.c` → 26 hits. For each, the enclosing
function was read start-to-end (not just to the first `return`), tracing
every early-return, every `goto`-based cleanup label, and — where the
pointer is the function's return value — whether it is legitimately
ownership-transferred to the caller (freed only on internal failure paths,
not before the final successful `return ptr`) versus actually leaked.

## Call sites and per-path free verdicts

| # | file:line | enclosing function | disposition |
|---|---|---|---|
| 1 | eap_fast_common.c:101 | `eap_fast_derive_key` | clean — `os_free(out)` on `tls_connection_prf` failure; on success `out` is **returned** (ownership transfer to caller), not freed here — correct |
| 2 | eap_ikev2_common.c:31 | `eap_ikev2_derive_keymat` | clean — `os_free(nonces)` on `ikev2_prf_plus` failure path and again on the success path before `return 0` |
| 3 | eap_eke_common.c:350 | `eap_eke_derive_key` | clean — `os_free(id)` on `eap_eke_prfplus` failure and on success path before `return 0` |
| 4 | eap_eke_common.c:484 | `eap_eke_derive_ke_ki` | clean — `os_free(data)` on failure and on success path |
| 5 | eap_eke_common.c:525 | `eap_eke_derive_ka` | clean — `os_free(data)` on failure and on success path |
| 6 | eap_eke_common.c:570 | `eap_eke_derive_msk` | clean — `os_free(data)` on failure and on success path |
| 7 | eap_gpsk_common.c:140 | `eap_gpsk_derive_keys_helper` (static) | clean — `os_free(data)` on first `gkdf()` failure; unconditional `os_free(data)` immediately after the first `gkdf()` succeeds (data not touched again) |
| 8 | eap_gpsk_common.c:298 | `eap_gpsk_derive_keys` | clean — single exit: `os_free(seed); return ret;` covers all switch-case outcomes (success and the `default:`/unknown-cipher failure) |
| 9 | eap_gpsk_common.c:371 | `eap_gpsk_derive_mid_helper` (static) | clean — same pattern as #7: `os_free(data)` on `gkdf()` failure and unconditionally right after success use |
| 10 | eap_gpsk_common.c:442 | `eap_gpsk_derive_session_id` | clean — single exit: `os_free(seed); return ret;` after the helper call, regardless of helper's return value |
| 11 | eap_pwd_common.c:159 | `compute_password_element` | clean — classic `goto fail` pattern; `fail:` label falls through into the same shared cleanup block that ends with `os_free(prfbuf)`, so both the success path and every `goto fail` converge on one free |
| 12 | eap_pwd_common.c:297 | `compute_keys` | clean — `os_free(cruft)` on both `hash == NULL` early-return branches, and `os_free(cruft)` unconditionally right after its last use (before the later unrelated `eap_pwd_kdf` failure return, which no longer touches `cruft`) |
| 13 | eap_sake_common.c:328 | `eap_sake_compute_mic` | clean — single exit: `os_free(tmp); return 0;` (only one early return, before the allocation, on a NULL check that doesn't involve `tmp`) |
| 14 | ikev2_common.c:404 | `ikev2_derive_auth_data` | clean — `os_free(sign_data)` on the combined `ikev2_prf_hash` failure branch and again on the success path before `return 0` |
| 15 | ikev2_common.c:496 | `ikev2_decrypt_payload` | clean — `os_free(decrypted)` on decrypt failure and on invalid-padding failure; on success `decrypted` is **returned** (ownership transfer), not freed here — correct |
| 16 | ikev2_common.c:651 | `ikev2_derive_sk_keys` | clean — `os_free(keybuf)` on `ikev2_prf_plus` failure and unconditionally later after all `SK_*` fields are populated from it |
| 17–23 | ikev2_common.c:663,671,679,687,695,703,711 | `ikev2_derive_sk_keys` (`keys->SK_d`, `SK_ai`, `SK_ar`, `SK_ei`, `SK_er`, `SK_pi`, `SK_pr`) | clean, but **ownership transfer, not local free** — these 7 allocations are stored into the caller-owned `struct ikev2_keys *keys`. On this function's own failure path (`!ikev2_keys_set(keys)`, i.e. any of the 7 allocations returned NULL), `ikev2_free_keys(keys)` is called and frees every non-NULL one of the 7. On success they are intentionally left allocated, to be freed later by `ikev2_free_keys()` from the key's owner (analogous to the case4 "ownership transfer" pattern) — not a leak |
| 24 | eap_sim_common.c:178 | `eap_sim_verify_mac` | clean — single exit: `os_free(tmp)` unconditionally before the final `return` (comparison result) |
| 25 | eap_sim_common.c:373 | `eap_sim_verify_mac_sha256` | clean — single exit: `os_free(tmp)` unconditionally before the final `return` |
| 26 | eap_sim_common.c:946 | `eap_sim_parse_encr` | clean — `os_free(decrypted)` on `aes_128_cbc_decrypt` failure and on `eap_sim_parse_attr` failure; on success `decrypted` is **returned** (ownership transfer), not freed here — correct |

## Verdict

**No leaks found.** All 26 `os_malloc()` call sites in `src/eap_common/*.c`
are correctly matched by `os_free()` on every exit path that owns the
buffer, or are legitimate ownership transfers (the pointer is returned to
the caller / stored into a caller-owned struct) whose *internal* error
paths are still fully freed. This includes 3 return-value ownership
transfers (#1, #15, #26) and 7 struct-field ownership transfers inside one
function (#16–23 covering `ikev2_derive_sk_keys`), all of which correctly
free on their own internal failure paths without freeing what they hand
back to the caller on success.

Two grouping subtleties a correct answer must get right (this is what
makes the question L3, not just "grep for os_malloc/os_free pairs"):

1. `ikev2_derive_sk_keys` (ikev2_common.c) has **8** `os_malloc()` call
   sites in one function (`keybuf` + the 7 `keys->SK_*` fields), and 7 of
   them are never freed *by this function* on the success path — that is
   correct (ownership transfer to the `keys` struct), not a leak. A naive
   "every os_malloc needs a nearby os_free in the same function" heuristic
   would misflag these 7 as leaks.
2. `eap_fast_derive_key`, `ikev2_decrypt_payload`, and `eap_sim_parse_encr`
   each return the malloc'd buffer as the function's result on success —
   again correct ownership transfer, not a missing free.

## Scoring rubric (0-3)

- **3**: Finds all (or materially all, allowing 1-2 missed of the 26) call
  sites in `src/eap_common/*.c`, correctly reports "no leaks", and
  explicitly distinguishes the ownership-transfer cases (#1, #15, #16-23,
  #26) from true local-free cases — i.e. doesn't just say "clean" but shows
  it understood *why* those don't call `os_free` on the happy path.
- **2**: Finds most call sites (roughly half or more) and correctly
  concludes "no leaks" for the ones examined, but does not distinguish
  ownership-transfer returns from local frees (treats everything as one
  undifferentiated "clean" bucket), or misses the multi-allocation
  structure of `ikev2_derive_sk_keys`.
- **1**: Only checks a handful of call sites (e.g. only one or two files),
  or reports a false-positive leak by stopping at the first return
  statement instead of reading the whole function (e.g. flags
  `ikev2_derive_sk_keys`'s `keys->SK_ai..SK_pr` as leaked because they see
  no `os_free` near the allocation), or misreads the question's scope and
  reports on `os_malloc` calls inside `os_unix.c` itself instead of on its
  callers in `src/eap_common/`.
- **0**: Wrong scope entirely (e.g. analyzes unrelated files, or a
  different allocator/function), or fabricates a leak/free that doesn't
  exist in the source, or gives up without enumerating call sites.
