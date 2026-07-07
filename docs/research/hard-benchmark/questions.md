# Questions — wpa_supplicant/redis 難題庫(人類可讀版)

> 機器可讀版:`questions.jsonl`。分類架構:`taxonomy.md`。

> `★ EXECUTED` 標記:原始 4 題(WRQ-008/009/013/017)是 v2 報告的真跑題(headless Claude Code A/B/C + 第三方工具),結果見 `../llm-ab-v2-hard-cases.md`。其餘 18 題原本只是文件化題庫,2026-07-07/08 為了 v3(全 22 題 × 4 工具 × Sonnet 5)全部補建了嚴謹 GT 並標記執行,結果見 `../llm-ab-v3-full-suite.md`,詳見各題 `evaluation_notes` 與對應的 `gt_WRQ-0XX.md` 檔案。

## symbol-definition

### WRQ-001 [wpa] [L1] ★ EXECUTED

**Question**: Find the definition of eloop_register_timeout(). Return file, line, and full signature.

**Expected schema**: file, line, signature

**Evaluation notes**: VERIFIED 2026-07-07. Definition: src/utils/eloop.c:601, `int eloop_register_timeout(unsigned int secs, unsigned int usecs, eloop_timeout_handler handler, void *eloop_data, void *user_data)`. eloop.h:179 confirmed a declaration only. Build-system note: a second, platform-alternate definition exists at src/utils/eloop_win.c:237 (selected only for native Windows builds via CONFIG_ELOOP=eloop_win) — not a competing answer since this question has no scope limiter, but citing eloop_win.c ALONE (missing the default eloop.c) should be scored down. Full detail: gt_WRQ-001.md.

**Purpose(驗證目的)**: 對照組:單點查找,驗證兩臂基本能力沒有退化,不是本輪重點。

### WRQ-002 [redis] [L1] ★ EXECUTED

**Question**: Find the definition of createStringObject(). Return file, line, and full signature.

**Expected schema**: file, line, signature

**Evaluation notes**: VERIFIED 2026-07-07. Definition: src/object.c:338, `robj *createStringObject(const char *ptr, size_t len)`. Declared at src/object.h:139 (not directly in server.h — server.h only pulls it in transitively via #include "object.h"). No Makefile gating (object.o compiled unconditionally). Confusable sibling names to watch for: tryCreateStringObject, createStringObjectFromLongLong(WithOptions/ForValue/WithSds), createStringObjectFromLongDouble. Full detail: gt_WRQ-002.md. CORRECTION 2026-07-08: this GT originally missed a real second, unrelated definition at deps/hiredis/hiredis.c:125 (a static, different-signature helper in the vendored hiredis client parser) -- misclassified in the first pass as 'just a call site'. All 4 v3-round agents correctly surfaced this real collision; noting it is precise, correct behavior and must not be scored down. See gt_WRQ-002.md for the full correction.

**Purpose(驗證目的)**: 對照組,驗證基本符號查找能力。

### WRQ-003 [wpa] [L2] ★ EXECUTED

**Question**: Find the definition of struct wpa_driver_ops. Return file, line, and total number of function-pointer fields.

**Expected schema**: file, line, field_count

**Evaluation notes**: VERIFIED 2026-07-07 — DRAFT NUMBER WAS WRONG. struct wpa_driver_ops defined at src/drivers/driver.h:1633. Actual function-pointer field count is **142**, not 136 (confirmed independently by 3 methods in the GT-construction pass AND spot-checked again directly: `awk` range-extract + regex count on `(*name)(` = 142). The '136' figure had been repeated uncritically in gt_case1_driver_ops.txt's header comment and in WRQ-009's own question text — it was never independently verified before this pass. 22 of the 142 are #ifdef-gated (1 ANDROID driver_cmd + 21 CONFIG_MACSEC fields); this repo's own .config defines neither, so an actual build only wires up 120. 142 (source-level) is the primary graded answer; 120-as-configured is bonus rigor. Full detail: gt_WRQ-003.md.

**Purpose(驗證目的)**: 為 case1(callback-indirect 真跑題)暖身:先確認兩臂都能正確數出 struct 總欄位數。

## references-usages

### WRQ-004 [wpa] [L2] ★ EXECUTED

**Question**: List every real code reference to eloop_remove_timeout() under src/, excluding any occurrence inside a string literal (e.g. debug log messages) or comment.

**Expected schema**: references

**Evaluation notes**: VERIFIED 2026-07-07. Total real references: 10, split across two platform-alternate eloop backends: src/utils/eloop.c (def 652; calls 674,702,1008,1084) and src/utils/eloop_win.c (def 285; calls 305,333,594,656) — each unconditionally compiled for its own target, no Makefile trap applies to either. Zero false positives (no wpa_printf/wpa_msg string or comment mentions the symbol) — this particular symbol has a clean answer set; the real difficulty is recall across two backend files, not precision filtering. Full detail: gt_WRQ-004.md.

**Purpose(驗證目的)**: 驗證 false-positive 過濾:log 訊息字串是這兩個 codebase 常見的假陽性來源。

### WRQ-005 [redis] [L2] ★ EXECUTED

**Question**: List every real code reference to decrRefCount() within src/t_string.c only, excluding comments.

**Expected schema**: references

**Evaluation notes**: VERIFIED 2026-07-07. Real reference count: exactly 7 (src/t_string.c lines 128,207,543,894,1347,1629,1630), all genuine decrRefCount(...) calls. Excluded comment at line 186 confirmed exact (not drifted). Cross-checked via grep -c and independent awk pass (both agree: 8 total hits = 7 real + 1 comment). No #ifdef gating in this file. Full detail: gt_WRQ-005.md.

**Purpose(驗證目的)**: 同上,驗證單檔範圍內的註解過濾。

## caller-callee

### WRQ-006 [wpa] [L3] ★ EXECUTED

**Question**: Function freq_cmp() in src/utils/common.c is never called directly. Find every place it is passed BY NAME as an argument (not called), and name the calling function and call site.

**Expected schema**: callback_sites

**Evaluation notes**: VERIFIED 2026-07-07. Exactly one by-name-passing site: int_array_sort_unique() at src/utils/common.c:895, `qsort(a, alen, sizeof(int), freq_cmp)`. Confirmed exhaustive via 3 independent grep methods (all return only the definition line 873 + this one site) and structurally guaranteed by freq_cmp's `static` linkage (no header prototype, so no other translation unit could reference it). No Makefile/​#ifdef gating on common.c. Scope trap noted: int_array_sort_unique()'s own callers (wpa_supplicant/scan.c, utils_module_tests.c) do NOT name freq_cmp and should not be credited. Full detail: gt_WRQ-006.md.

**Purpose(驗證目的)**: 重出先前 5 題裡驗證過的一題,作為本輪與舊輪的可比較錨點(同一題,不同 harness/更難的伴隨題組)。

### WRQ-007 [redis] [L3] ★ EXECUTED

**Question**: Find every function in src/t_string.c that calls setKeyByLink() (defined in src/db.c), directly or by first calling setGenericCommand().

**Expected schema**: callers, call_depth

**Evaluation notes**: VERIFIED 2026-07-07. Exactly 5 functions in src/t_string.c reach setKeyByLink(): setGenericCommand (depth 1, t_string.c:87→181), setCommand/setnxCommand/setexCommand/psetexCommand (depth 2, each calling setGenericCommand). getexCommand/increxCommand do NOT reach it (they only call setExpire, a sibling). The mset* family DOES reach setKeyByLink but only via a third, unlisted path (setKey() wrapper in db.c:742) — correctly excluded per the question's literal wording ("directly or by first calling setGenericCommand()"). No #ifdef/Makefile gating on either file. Full detail: gt_WRQ-007.md.

**Purpose(驗證目的)**: entry-path 真跑題(WRQ-008)的簡化前導版:先測單跳以上的 caller 追蹤能力。

## entry-path

### WRQ-008 [redis] [L4] ★ EXECUTED

**Question**: Trace the full call path from Redis command dispatch to the lowest-level database write for the SET command: from lookupCommand()/processCommand() through setCommand(), setGenericCommand(), down to the actual key-value write in db.c. List every named hop in order, with file and line for each.

**Expected schema**: call_path

**Evaluation notes**: Full GT chain (docs/research/hard-benchmark/gt_case2_set_chain.md): processCommand -> lookupCommand -> (cmd->proc) setCommand(t_string.c:435) -> setGenericCommand -> lookupKeyWriteWithLink (existence check) -> setKeyByLink(db.c:754) -> [exists] dbSetValue + notifyKeyspaceEvent(overwritten) OR [!exists] dbAddByLink(db.c:460) -> dbAddInternal; then keyModified + notifyKeyspaceEvent(set). Score 3 requires naming setKeyByLink AND the exists/!exists branch split; score 2 stops at setGenericCommand without the branch.

**Purpose(驗證目的)**: 真跑題。測多跳呼叫鏈追蹤;grep 臂通常一次只能看一跳,容易在 setKeyByLink 這個中間層斷掉或漏看 exists/不存在的分支。

## callback-indirect

### WRQ-009 [wpa] [L3] ★ EXECUTED

**Question**: struct wpa_driver_ops has 136 function-pointer fields. For the nl80211 driver backend (src/drivers/driver_nl80211.c, the wpa_driver_nl80211_ops struct literal), list EVERY field that is filled in, paired with the implementing function name. Do not stop partway through the struct literal.

**Expected schema**: field_to_function_pairs, total_filled_count

**Evaluation notes**: Full GT (docs/research/hard-benchmark/gt_case1_driver_ops.txt): 96 of 136 fields filled. Score 3 requires all or nearly all 96 pairs correct; score 2 = found most but stopped before the end of the ~230-line struct literal (a common grep/Read failure mode); score 1 = only the first ~20-30 fields (matches the visible portion of one Read call).

**Purpose(驗證目的)**: 真跑題。規模差異化:舊題只驗證 5 個 handler,這題 96 個,測工具/agent 是否會在大型 struct literal 中途放棄。

### WRQ-010 [redis] [L3] ★ EXECUTED

**Question**: redis object types (e.g. OBJ_ENCODING_* handling in t_string.c / object.c) dispatch on obj->encoding via switch statements rather than a function-pointer ops table. Confirm whether redis's string type uses any function-pointer dispatch table (like moduleTypeMethods) versus wpa's ops-table pattern, and explain the difference in indirection style found.

**Expected schema**: dispatch_mechanism_description

**Evaluation notes**: VERIFIED 2026-07-07 — deliberate hallucination-trap question. Core object/string dispatch (object.c, t_string.c, t_list.c, t_hash.c) uses switch/if on o->encoding or o->type — NOT a function-pointer table (evidence: object.c:434,550,567,586,643-681,1290; t_list.c:452; t_hash.c:2078). A REAL function-pointer ops table exists only for Modules: RedisModuleTypeMethods (redismodule.h:1051) / moduleType (server.h:955), invoked via mv->type->free(...) in freeModuleObject (object.c:605), reached only via the distinct OBJ_MODULE case — core types never touch it. Rubric scores 0-1 for fabricating a fake core-type ops table. Full detail: gt_WRQ-010.md.

**Purpose(驗證目的)**: 題庫廣度:測工具能否正確回報「這裡沒有 fnptr 分派」而不是硬湊一個不存在的 callback 邊。

## data-structure

### WRQ-011 [wpa] [L2] ★ EXECUTED

**Question**: Find the definition of struct dl_list in src/utils/list.h and list every function in src/utils/list.c that operates on it (insert/remove/iterate).

**Expected schema**: struct_fields, operating_functions

**Evaluation notes**: VERIFIED 2026-07-07 — THE QUESTION'S OWN PREMISE IS WRONG. src/utils/list.c does not exist in this repo (confirmed via find/git log --all/Makefile grep — never existed, not build-gated). struct dl_list (list.h:15-18: next/prev). All 6 operating functions (dl_list_init, dl_list_add, dl_list_add_tail, dl_list_del, dl_list_empty, dl_list_len) plus iteration macros (dl_list_for_each etc.) are static inline / macros defined directly in list.h, none in a nonexistent list.c. Independently spot-checked (find + grep -c "static inline" = 6): confirmed. Rubric treats correctly flagging the missing file and redirecting to the header as full credit (3); silently treating header content as if from list.c scores 2; fabricating a fake list.c scores 0-1. Full detail: gt_WRQ-011.md.

**Purpose(驗證目的)**: 題庫廣度,不排入真跑(container_of 類推理在此二 codebase 不夠鮮明)。

### WRQ-012 [redis] [L2] ★ EXECUTED

**Question**: Find the definition of the robj struct (or kvobj if robj is now an alias) and list which fields determine its reference-counting behavior.

**Expected schema**: struct_fields, refcount_field

**Evaluation notes**: VERIFIED 2026-07-07. Struct is `redisObject` (src/object.h:100-112); both `robj` and `kvobj` are currently plain typedef aliases of the SAME struct in this checkout (no separate kvobj type yet — distinguished only by the iskvobj:1 bitfield). Refcount-governing fields/constants: refcount (bitfield, object.c incr/decrRefCount), OBJ_SHARED_REFCOUNT (object.h:96, shared/immutable sentinel), OBJ_STATIC_REFCOUNT (object.h:97, stack-allocated sentinel, incrRefCount panics if retained), OBJ_FIRST_SPECIAL_REFCOUNT (threshold aliasing OBJ_STATIC_REFCOUNT). iskvobj gates which free path runs at refcount 0 but isn't itself a counter. lru is a common false-positive (bit-packed adjacent to refcount) flagged explicitly in the rubric. Full detail: gt_WRQ-012.md.

**Purpose(驗證目的)**: 題庫廣度。

## kconfig-build

### WRQ-013 [wpa] [L4] ★ EXECUTED

**Question**: wpa_supplicant has ~1985 `#ifdef CONFIG_*` conditional blocks. For CONFIG_SAE specifically, list every FUNCTION (not just file or line) whose compiled behavior depends on it, across the whole src/ tree. For each function, classify whether the ENTIRE function only exists under CONFIG_SAE ("whole"), or the function always exists but only PART of its body is conditional ("partial").

**Expected schema**: function_list_with_gate_type

**Evaluation notes**: GT CORRECTED TWICE. Round 1 (2026-07-06, after the original A/B run): discovered the Makefile whole-file gate for src/common/sae.c (35 functions, wpa_supplicant/Makefile:241-243 `ifdef CONFIG_SAE ... OBJS += ../src/common/sae.o ... endif`) that the naive grep-based original GT (19 whole) had missed -- but ALSO wrongly folded in 5 functions from wpa_supplicant/sme.c, arriving at a mistaken 'true' whole-count of 54. Round 2 (2026-07-07, after running CodeGraph and cbm on this same question with Opus 4.8 as a third-party comparison): both third-party tools independently arrived at 49 whole (35 sae.c + 14 ieee802_11.c) + 9 partial = 58 total -- and cbm explicitly flagged that wpa_supplicant/sme.c, mesh_rsn.c, and config.c are OUTSIDE the src/ tree and excluded them per the question's own literal wording ('across the whole src/ tree'). Verified: sme.c lives at wpa_supplicant/sme.c, a SIBLING of src/ at the repo root (not nested under it) -- so the round-1 correction that added sme.c's functions was itself an error, not a fix; the question's literal scope means sme.c is legitimately out of bounds. TRUE final count: Whole=49 (35 in src/common/sae.c, Makefile-gated, zero internal #ifdef; 14 in src/ap/ieee802_11.c, one contiguous #ifdef block lines 318-876), Partial=9 (handle_auth + check_assoc_ies in ieee802_11.c; wpa_write_rsn_ie + wpa_validate_wpa_ie in wpa_auth_ie.c; wpa_gen_wpa_ie_rsn in wpa_ie.c; rsn_key_mgmt_to_bitfield in wpa_common.c; hostapd_wpa_auth_get_psk in wpa_auth_glue.c; ap_free_sta in sta_info.c; hostapd_ctrl_iface_sta_mib in ctrl_iface_ap.c), Total=58 functions across 8 files. This is exactly what BOTH of the ORIGINAL ccodegraph A/B arms answered in the very first run (before any 'correction') -- meaning their original score of 2/3 (docked for 'missing sme.c') was actually WRONG; re-scored to 3/3. Lesson: when hand-correcting a GT after seeing agent answers, re-read the question's own literal scope constraint before accepting an 'the agent missed something' framing -- the agent may be right and the grader wrong. See docs/research/llm-ab-v2-hard-cases.md for the full narrative.

**GT correction record**: Round-0 (pre-2026-07-06) evaluation_notes only covered inline #ifdef in sme.c+ieee802_11.c (19 whole), missing the Makefile whole-file gate for sae.c (35 more). Round-1 (2026-07-06) 'corrected' this to 54 by adding sme.c's 5 functions -- itself later found wrong in round-2 (2026-07-07) because sme.c is outside the src/ tree the question is literally scoped to. Kept here for the record of how the GT evolved across two correction rounds.

**Purpose(驗證目的)**: 真跑題,四題中設計目的最明確的一題:直接檢驗 ccodegraph 語意層(semantic:confirmed|absent)對條件編譯的誠實標記能力,以及 grep 對巢狀 #ifdef 邊界判斷、行號到函式歸戶的已知弱點。

### WRQ-014 [redis] [L2] ★ EXECUTED

**Question**: Find every place in the redis source tree gated by `#ifdef USE_JEMALLOC` or `#ifdef HAVE_BACKTRACE`, and report which SUBSYSTEM each belongs to (memory allocator vs crash/debug reporting).

**Expected schema**: gated_locations, subsystem_classification

**Evaluation notes**: VERIFIED 2026-07-07. USE_JEMALLOC (memory-allocator subsystem): 13 files in src/ (zmalloc.c/h, sds.c, object.c, server.c, db.c, lazyfree.c, cluster_asm.c, eval.c, function_lua.c, script.c, syscheck.c, debug.c(3 sites)) — all confirmed by reading surrounding code, not filename-guessed. HAVE_BACKTRACE (crash/debug subsystem): all 15 occurrences confined to src/debug.c alone. Build-system effect found: src/Makefile has real ifeq blocks (lines 84-106, 301-305) deciding whether the whole external deps/jemalloc library gets built/linked — bigger than any single .c file, but does NOT conditionally add an extra redis .c file (REDIS_SERVER_OBJ is static regardless of MALLOC). HAVE_BACKTRACE by contrast has zero Makefile conditional — pure platform/libc detection via src/config.h:72. Full detail: gt_WRQ-014.md.

**Purpose(驗證目的)**: 題庫廣度,較簡單的版本(不要求函式層級判斷),留作對照。

## include-dependency

### WRQ-015 [wpa] [L2] ★ EXECUTED

**Question**: Which .c files directly #include "eloop.h"? Give an exact count and confirm whether the count matches a transitive closure via any header that itself includes eloop.h.

**Expected schema**: direct_includers, transitive_note

**Evaluation notes**: VERIFIED 2026-07-07 — literal grep undercounts by half. Naive `#include "eloop.h"` grep = 59 files. TRUE count = 117: 58 more files use the alternate spelling `#include "utils/eloop.h"` (zero overlap with the 59), which resolves to the identical physical header because wpa_supplicant/Makefile sets `-I ../src` and `-I ../src/utils` unconditionally for every build (not behind any ifdef). Transitive closure is empty (no header itself includes eloop.h in either spelling), so the 117 direct includers ARE the complete dependent set — but only because there's no further transitive contribution, not because of any dedup. Rubric caps score at 2/3 for stopping at 59. Full detail: gt_WRQ-015.md.

**Purpose(驗證目的)**: 題庫廣度,先前已測過直接 include,這題加了遞移閉包的追問。

### WRQ-016 [redis] [L1] ★ EXECUTED

**Question**: How many .c files directly #include "server.h"?

**Expected schema**: count

**Evaluation notes**: VERIFIED 2026-07-07. Exact count: 70 .c files directly #include "server.h" under src/ (verified two ways: file-count and per-file occurrence-count, both = 70, no duplicates). Whole-repo search confirms deps/, tests/, modules/ contribute zero additional files — no real scope ambiguity. Full detail: gt_WRQ-016.md.

**Purpose(驗證目的)**: 對照組。

## dataflow-lifetime

### WRQ-017 [redis] [L4] ★ EXECUTED

**Question**: In src/t_string.c, every call to createStringObject/createStringObjectFromLongLong/createStringObjectFromLongDouble/createStringObjectFromLongLongForValue allocates a fresh object. For EACH such allocation site, determine whether the object is (a) locally freed via decrRefCount within the SAME function, or (b) its ownership is transferred elsewhere (e.g., handed to the database as the new value) and therefore has no local decrRefCount. List both categories separately.

**Expected schema**: allocation_sites, local_free_pairs, ownership_transfer_sites

**Evaluation notes**: Full GT (docs/research/hard-benchmark/gt_case4_lifecycle.md): 5 locally-freed pairs (setGenericCommand, getexCommand, msetexCommand, increxCommand each create/decrRefCount a milliseconds_obj temp; lcsCommand creates/frees two comparison temps obja/objb) vs 3 ownership-transfer functions (incrDecrCommand, incrbyfloatCommand, increxCommand's 'new' value object -- these are handed to the key-write path and freed later, not in this function). Score 3 = correctly separates both categories; score 2 = finds all allocation sites but treats ownership-transfer sites as bugs/leaks or omits them; score 1 = only the easy local-pair cases.

**Purpose(驗證目的)**: 真跑題,四題中最難:這是真正的資料流推理,不是關係查詢。設計目的是檢驗能否分辨『沒有局部釋放』的兩種完全不同原因(所有權轉移 vs 真正遺漏),grep 對兩者的文字特徵是一樣的(都是『create 有、同函式 decrRefCount 沒有』),必須讀語意才能分辨。

### WRQ-018 [wpa] [L3] ★ EXECUTED

**Question**: Find every os_malloc() call in src/utils/os_unix.c's callers within src/eap_common/ and confirm each has a matching os_free() on all exit paths (including error paths).

**Expected schema**: allocation_sites, free_sites, unmatched_paths

**Evaluation notes**: VERIFIED 2026-07-07. Clarified scope: question means functions in src/eap_common/*.c calling os_malloc() (not os_unix.c's own internal calls, which are just the allocator's own implementation). Found 26 call sites across 8 files. Verdict: NO LEAKS anywhere — 14 are local alloc/free pairs (freed on both the internal-failure and normal-completion paths, incl. goto-based cleanup converging correctly), 3 are return-value ownership transfers (correctly left unfreed on success, freed on every internal error path), 7 are struct-field ownership transfers inside one function (ikev2_derive_sk_keys, ikev2_common.c:663-711 — freed via ikev2_free_keys() on partial failure, intentionally left for the caller on success). Rubric penalizes misflagging the 7 transferred fields or 3 return-transfer buffers as leaks from stopping analysis at the first return. Full detail: gt_WRQ-018.md.

**Purpose(驗證目的)**: 題庫廣度,wpa 版的生命週期題,聚焦錯誤路徑而非所有權轉移(與 redis 真跑題互補、不重複)。

## locking-rcu

### WRQ-019 [redis] [L3] ★ EXECUTED

**Question**: bio.c spawns a background thread via pthread_create for bioProcessBackgroundJobs. List every piece of shared state (global variables or struct fields) this background thread reads or writes that the main thread also touches, and identify what synchronization primitive (if any) protects each.

**Expected schema**: shared_state, sync_primitives

**Evaluation notes**: VERIFIED 2026-07-07 — draft hint was half-wrong. bioInit() spawns 3 threads (BIO_WORKER_NUM=3, not 1), all running bioProcessBackgroundJobs. Shared state: bio_jobs[3] + bio_jobs_counter[7], guarded by bio_mutex[worker] (PER-WORKER, not per-job-type as the draft note claimed — 7 job types map onto only 3 workers); bio_comp_list guarded by a SEPARATE single mutex bio_mutex_comp (a common miss); job_comp_pipe[2] has NO mutex (safe via POSIX write-atomicity + happens-before at thread creation); three AOF-fsync status fields (server.aof_bio_fsync_status/errno, fsynced_reploff_pending) are redisAtomic-qualified — lock-free compiler atomics, not a mutex; server.bio_cpulist has no lock (safe because IMMUTABLE_CONFIG, set before threads spawn). Explicit non-shared exclusions flagged: bio_threads[], bio_worker_title[]/bio_job_to_worker[], errno. Full detail: gt_WRQ-019.md.

**Purpose(驗證目的)**: 題庫廣度,redis 特有(wpa 單執行緒不適用,taxonomy.md 已誠實記錄原因)。本輪不排真跑:前置知識要求高,四個真跑題已涵蓋『多跳/大規模/條件編譯/資料流』四種能力,並發模型留待未來擴充。

### WRQ-020 [wpa] [N/A] ★ EXECUTED

**Question**: Does wpa_supplicant's core event loop (src/utils/eloop.c) use any locks, mutexes, or RCU-style synchronization for its timeout/socket registration lists?

**Expected schema**: applicability_note

**Evaluation notes**: VERIFIED 2026-07-07 — trap question, draft hint confirmed correct with hard evidence. src/utils/eloop.c has zero pthread/lock/RCU/semaphore symbols (grep confirmed on all common patterns). Repo-wide: zero `pthread_*` symbols exist ANYWHERE in the checkout — no thread is ever spawned that could concurrently touch eloop's dl_list-based timeout/socket registration. Rubric explicitly ranks confident fabrication (inventing mutexes/RCU that don't exist) as the worst outcome (0), below a terse unsupported-but-correct 'no' (1), below a correct answer with partial evidence (2), full credit (3) requires both the correct 'no' and the pthread_create absence-check. Full detail: gt_WRQ-020.md.

**Purpose(驗證目的)**: 刻意的『陷阱』對照題:正確答案是『此類不適用』,測工具會不會硬湊出不存在的鎖語意分析(誠實原則的反向測試)。

## bug-localization

### WRQ-021 [wpa] [L3] ★ EXECUTED

**Question**: A user reports wpa_supplicant returning a generic 'scan failed' error from the nl80211 driver backend. Find the function(s) in src/drivers/driver_nl80211.c that construct scan-trigger failure return paths, and list the distinct conditions under which each returns an error for a scan request.

**Expected schema**: error_construction_sites, conditions

**Evaluation notes**: VERIFIED 2026-07-07 — file-scope trap. In THIS checkout, src/drivers/driver_nl80211.c contains only ONE scan-related function, driver_nl80211_scan2 (line 7223-7228), a 3-line forwarding wrapper with zero error conditions of its own. The real scan-trigger logic (and its distinct error-return conditions: netlink-attribute build failures, P2P-probe rate-mask failures, kernel/netlink rejection with AP-mode-retry vs. immediate-failure sub-branches) lives in a SIBLING translation unit, src/drivers/driver_nl80211_scan.c — confirmed at the build-system level (drivers.mak lists driver_nl80211_scan.o as a separate object, not a #include). Rubric caps score at 2/3 for answers that get the error-condition content right but misattribute it to driver_nl80211.c itself; full credit requires respecting the question's explicit file-scope limiter while still surfacing where the logic actually lives. Full detail: gt_WRQ-021.md.

**Purpose(驗證目的)**: 題庫廣度:適配 kernel 的 bug-localization 類,改成『找建構錯誤訊息的函式與條件』而非單純 grep 字串。

### WRQ-022 [redis] [L2] ★ EXECUTED

**Question**: A user sees a WRONGTYPE error when running SET on an existing key. Find where this specific error reply is constructed in the SET command path (not other commands).

**Expected schema**: error_construction_site

**Evaluation notes**: VERIFIED 2026-07-07. Plain SET on an existing key never WRONGTYPE-checks (overwrites unconditionally). WRONGTYPE from SET only fires via two option-gated branches inside setGenericCommand (t_string.c:87), both reachable only when command_type==COMMAND_SET: (A) the GET option, via getGenericCommand's checkType call at t_string.c:467; (B) the IFEQ/IFNE/IFDEQ/IFDNE options, direct inline checkType call at setGenericCommand:117-119. Both terminate in the shared helper checkType() (object.c:884-891), whose line object.c:887 (addReplyErrorObject(c,shared.wrongtypeerr)) is the actual construction site. Scope trap: the t_string.c:467 call site is textually identical whether reached from GET's own dispatch or SET's GET-option — what makes it 'SET's' is the caller, not the callee. Rubric scores 0 for attributing GET/GETEX/LPUSH's own checkType calls to SET. Full detail: gt_WRQ-022.md.

**Purpose(驗證目的)**: 題庫廣度,較簡單版本,對照題。
