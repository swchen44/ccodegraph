# Questions — wpa_supplicant/redis 難題庫(人類可讀版)

> 機器可讀版:`questions.jsonl`。分類架構:`taxonomy.md`。

> `★ EXECUTED` 標記的 4 題是本輪真跑(headless Claude Code A/B),結果與評分見
`../llm-ab-v2-hard-cases.md`。其餘 18 題是文件化題庫,留待未來擴充,本輪不執行。


## symbol-definition

### WRQ-001 [wpa] [L1]

**Question**: Find the definition of eloop_register_timeout(). Return file, line, and full signature.

**Expected schema**: file, line, signature

**Evaluation notes**: Must be the definition in src/utils/eloop.c, not the declaration in eloop.h.

**Purpose(驗證目的)**: 對照組:單點查找,驗證兩臂基本能力沒有退化,不是本輪重點。

### WRQ-002 [redis] [L1]

**Question**: Find the definition of createStringObject(). Return file, line, and full signature.

**Expected schema**: file, line, signature

**Evaluation notes**: Definition in src/object.c, not any forward declaration in server.h.

**Purpose(驗證目的)**: 對照組,驗證基本符號查找能力。

### WRQ-003 [wpa] [L2]

**Question**: Find the definition of struct wpa_driver_ops. Return file, line, and total number of function-pointer fields.

**Expected schema**: file, line, field_count

**Evaluation notes**: Correct field count is 136. Off-by-a-few answers should be flagged (evidence of not reading the whole struct).

**Purpose(驗證目的)**: 為 case1(callback-indirect 真跑題)暖身:先確認兩臂都能正確數出 struct 總欄位數。


## references-usages

### WRQ-004 [wpa] [L2]

**Question**: List every real code reference to eloop_remove_timeout() under src/, excluding any occurrence inside a string literal (e.g. debug log messages) or comment.

**Expected schema**: references

**Evaluation notes**: Must filter false positives from wpa_printf() log strings that happen to mention the function name.

**Purpose(驗證目的)**: 驗證 false-positive 過濾:log 訊息字串是這兩個 codebase 常見的假陽性來源。

### WRQ-005 [redis] [L2]

**Question**: List every real code reference to decrRefCount() within src/t_string.c only, excluding comments.

**Expected schema**: references

**Evaluation notes**: src/t_string.c has decrRefCount mentioned in a comment near line 186 that must be excluded.

**Purpose(驗證目的)**: 同上,驗證單檔範圍內的註解過濾。


## caller-callee

### WRQ-006 [wpa] [L3]

**Question**: Function freq_cmp() in src/utils/common.c is never called directly. Find every place it is passed BY NAME as an argument (not called), and name the calling function and call site.

**Expected schema**: callback_sites

**Evaluation notes**: freq_cmp is passed to qsort() inside int_array_sort_unique(); a direct-call search will find nothing.

**Purpose(驗證目的)**: 重出先前 5 題裡驗證過的一題,作為本輪與舊輪的可比較錨點(同一題,不同 harness/更難的伴隨題組)。

### WRQ-007 [redis] [L3]

**Question**: Find every function in src/t_string.c that calls setKeyByLink() (defined in src/db.c), directly or by first calling setGenericCommand().

**Expected schema**: callers, call_depth

**Evaluation notes**: setCommand, getexCommand family and others funnel through setGenericCommand -> setKeyByLink; a shallow one-hop search misses the indirection.

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

### WRQ-010 [redis] [L3]

**Question**: redis object types (e.g. OBJ_ENCODING_* handling in t_string.c / object.c) dispatch on obj->encoding via switch statements rather than a function-pointer ops table. Confirm whether redis's string type uses any function-pointer dispatch table (like moduleTypeMethods) versus wpa's ops-table pattern, and explain the difference in indirection style found.

**Expected schema**: dispatch_mechanism_description

**Evaluation notes**: This is a conceptual/comparative question — the correct answer notes redis modules use moduleTypeMethods (real ops table) while core string type uses switch/encoding, unlike wpa's pervasive ops-table pattern.

**Purpose(驗證目的)**: 題庫廣度:測工具能否正確回報「這裡沒有 fnptr 分派」而不是硬湊一個不存在的 callback 邊。


## data-structure

### WRQ-011 [wpa] [L2]

**Question**: Find the definition of struct dl_list in src/utils/list.h and list every function in src/utils/list.c that operates on it (insert/remove/iterate).

**Expected schema**: struct_fields, operating_functions

**Evaluation notes**: dl_list is wpa's hand-rolled doubly-linked list; functions include dl_list_add, dl_list_add_tail, dl_list_del, dl_list_len, dl_list_first/last.

**Purpose(驗證目的)**: 題庫廣度,不排入真跑(container_of 類推理在此二 codebase 不夠鮮明)。

### WRQ-012 [redis] [L2]

**Question**: Find the definition of the robj struct (or kvobj if robj is now an alias) and list which fields determine its reference-counting behavior.

**Expected schema**: struct_fields, refcount_field

**Evaluation notes**: Must find the actual current struct (naming may have changed across redis versions), not a stale online reference.

**Purpose(驗證目的)**: 題庫廣度。


## kconfig-build

### WRQ-013 [wpa] [L4] ★ EXECUTED

**Question**: wpa_supplicant has ~1985 `#ifdef CONFIG_*` conditional blocks. For CONFIG_SAE specifically, list every FUNCTION (not just file or line) whose compiled behavior depends on it, across the whole src/ tree. For each function, classify whether the ENTIRE function only exists under CONFIG_SAE ("whole"), or the function always exists but only PART of its body is conditional ("partial").

**Expected schema**: function_list_with_gate_type

**Evaluation notes**: GT CORRECTED TWICE. Round 1 (2026-07-06, after the original A/B run): discovered the Makefile whole-file gate for src/common/sae.c (35 functions, wpa_supplicant/Makefile:241-243 `ifdef CONFIG_SAE ... OBJS += ../src/common/sae.o ... endif`) that the naive grep-based original GT (19 whole) had missed — but ALSO wrongly folded in 5 functions from wpa_supplicant/sme.c, arriving at a mistaken "true" whole-count of 54. Round 2 (2026-07-07, after running CodeGraph and cbm on this same question with Opus 4.8 as a third-party comparison): both third-party tools independently arrived at 49 whole (35 sae.c + 14 ieee802_11.c) + 9 partial = 58 total — and cbm explicitly flagged that wpa_supplicant/sme.c, mesh_rsn.c, and config.c are OUTSIDE the src/ tree and excluded them per the question's own literal wording ("across the whole src/ tree"). Verified: sme.c lives at wpa_supplicant/sme.c, a SIBLING of src/ at the repo root (not nested under it) — so the round-1 correction that added sme.c's functions was itself an error, not a fix; the question's literal scope means sme.c is legitimately out of bounds. TRUE final count: Whole=49 (35 in src/common/sae.c, Makefile-gated, zero internal #ifdef; 14 in src/ap/ieee802_11.c, one contiguous #ifdef block lines 318–876), Partial=9 (handle_auth + check_assoc_ies in ieee802_11.c; wpa_write_rsn_ie + wpa_validate_wpa_ie in wpa_auth_ie.c; wpa_gen_wpa_ie_rsn in wpa_ie.c; rsn_key_mgmt_to_bitfield in wpa_common.c; hostapd_wpa_auth_get_psk in wpa_auth_glue.c; ap_free_sta in sta_info.c; hostapd_ctrl_iface_sta_mib in ctrl_iface_ap.c), Total=58 functions across 8 files. This is exactly what BOTH of the ORIGINAL ccodegraph A/B arms answered in the very first run (before any "correction") — meaning their original score of 2/3 (docked for "missing sme.c") was actually WRONG; re-scored to 3/3. Lesson: when hand-correcting a GT after seeing agent answers, re-read the question's own literal scope constraint before accepting an "the agent missed something" framing — the agent may be right and the grader wrong. See `docs/research/llm-ab-v2-hard-cases.md` for the full narrative.

**GT correction record**: Round-0 (pre-2026-07-06) evaluation_notes only covered inline #ifdef in sme.c+ieee802_11.c (19 whole), missing the Makefile whole-file gate for sae.c (35 more). Round-1 (2026-07-06) "corrected" this to 54 by adding sme.c's 5 functions — itself later found wrong in round-2 (2026-07-07) because sme.c is outside the src/ tree the question is literally scoped to. Kept here for the record of how the GT evolved across two correction rounds.

**Purpose(驗證目的)**: 真跑題,四題中設計目的最明確的一題:直接檢驗 ccodegraph 語意層(semantic:confirmed|absent)對條件編譯的誠實標記能力,以及 grep 對巢狀 #ifdef 邊界判斷、行號到函式歸戶的已知弱點。

### WRQ-014 [redis] [L2]

**Question**: Find every place in the redis source tree gated by `#ifdef USE_JEMALLOC` or `#ifdef HAVE_BACKTRACE`, and report which SUBSYSTEM each belongs to (memory allocator vs crash/debug reporting).

**Expected schema**: gated_locations, subsystem_classification

**Evaluation notes**: USE_JEMALLOC concentrates in zmalloc.c/server.h; HAVE_BACKTRACE concentrates in debug.c.

**Purpose(驗證目的)**: 題庫廣度,較簡單的版本(不要求函式層級判斷),留作對照。


## include-dependency

### WRQ-015 [wpa] [L2]

**Question**: Which .c files directly #include "eloop.h"? Give an exact count and confirm whether the count matches a transitive closure via any header that itself includes eloop.h.

**Expected schema**: direct_includers, transitive_note

**Evaluation notes**: Direct include count established in a prior benchmark round; this question additionally asks whether any header re-exports eloop.h transitively.

**Purpose(驗證目的)**: 題庫廣度,先前已測過直接 include,這題加了遞移閉包的追問。

### WRQ-016 [redis] [L1]

**Question**: How many .c files directly #include "server.h"?

**Expected schema**: count

**Evaluation notes**: Simple count; server.h is redis's central header so this should be a large fraction of all .c files.

**Purpose(驗證目的)**: 對照組。


## dataflow-lifetime

### WRQ-017 [redis] [L4] ★ EXECUTED

**Question**: In src/t_string.c, every call to createStringObject/createStringObjectFromLongLong/createStringObjectFromLongDouble/createStringObjectFromLongLongForValue allocates a fresh object. For EACH such allocation site, determine whether the object is (a) locally freed via decrRefCount within the SAME function, or (b) its ownership is transferred elsewhere (e.g., handed to the database as the new value) and therefore has no local decrRefCount. List both categories separately.

**Expected schema**: allocation_sites, local_free_pairs, ownership_transfer_sites

**Evaluation notes**: Full GT (docs/research/hard-benchmark/gt_case4_lifecycle.md): 5 locally-freed pairs (setGenericCommand, getexCommand, msetexCommand, increxCommand each create/decrRefCount a milliseconds_obj temp; lcsCommand creates/frees two comparison temps obja/objb) vs 3 ownership-transfer functions (incrDecrCommand, incrbyfloatCommand, increxCommand's 'new' value object -- these are handed to the key-write path and freed later, not in this function). Score 3 = correctly separates both categories; score 2 = finds all allocation sites but treats ownership-transfer sites as bugs/leaks or omits them; score 1 = only the easy local-pair cases.

**Purpose(驗證目的)**: 真跑題,四題中最難:這是真正的資料流推理,不是關係查詢。設計目的是檢驗能否分辨『沒有局部釋放』的兩種完全不同原因(所有權轉移 vs 真正遺漏),grep 對兩者的文字特徵是一樣的(都是『create 有、同函式 decrRefCount 沒有』),必須讀語意才能分辨。

### WRQ-018 [wpa] [L3]

**Question**: Find every os_malloc() call in src/utils/os_unix.c's callers within src/eap_common/ and confirm each has a matching os_free() on all exit paths (including error paths).

**Expected schema**: allocation_sites, free_sites, unmatched_paths

**Evaluation notes**: This targets a specific known-tricky pattern: error-path early returns that might skip cleanup.

**Purpose(驗證目的)**: 題庫廣度,wpa 版的生命週期題,聚焦錯誤路徑而非所有權轉移(與 redis 真跑題互補、不重複)。


## locking-rcu

### WRQ-019 [redis] [L3]

**Question**: bio.c spawns a background thread via pthread_create for bioProcessBackgroundJobs. List every piece of shared state (global variables or struct fields) this background thread reads or writes that the main thread also touches, and identify what synchronization primitive (if any) protects each.

**Expected schema**: shared_state, sync_primitives

**Evaluation notes**: bio.c uses its own mutex/condvar pair per job type; look for pthread_mutex_lock/pthread_cond_wait around the shared job queue.

**Purpose(驗證目的)**: 題庫廣度,redis 特有(wpa 單執行緒不適用,taxonomy.md 已誠實記錄原因)。本輪不排真跑:前置知識要求高,四個真跑題已涵蓋『多跳/大規模/條件編譯/資料流』四種能力,並發模型留待未來擴充。

### WRQ-020 [wpa] [N/A]

**Question**: Does wpa_supplicant's core event loop (src/utils/eloop.c) use any locks, mutexes, or RCU-style synchronization for its timeout/socket registration lists?

**Expected schema**: applicability_note

**Evaluation notes**: Expected correct answer is 'no — eloop is single-threaded per process, dl_list operations are not synchronized because there is no concurrent access'. A tool that fabricates lock analysis here is wrong.

**Purpose(驗證目的)**: 刻意的『陷阱』對照題:正確答案是『此類不適用』,測工具會不會硬湊出不存在的鎖語意分析(誠實原則的反向測試)。


## bug-localization

### WRQ-021 [wpa] [L3]

**Question**: A user reports wpa_supplicant returning a generic 'scan failed' error from the nl80211 driver backend. Find the function(s) in src/drivers/driver_nl80211.c that construct scan-trigger failure return paths, and list the distinct conditions under which each returns an error for a scan request.

**Expected schema**: error_construction_sites, conditions

**Evaluation notes**: Centers on wpa_driver_nl80211_scan/scan2 and their nl80211 command-send error handling.

**Purpose(驗證目的)**: 題庫廣度:適配 kernel 的 bug-localization 類,改成『找建構錯誤訊息的函式與條件』而非單純 grep 字串。

### WRQ-022 [redis] [L2]

**Question**: A user sees a WRONGTYPE error when running SET on an existing key. Find where this specific error reply is constructed in the SET command path (not other commands).

**Expected schema**: error_construction_site

**Evaluation notes**: Should land on the type-check inside setGenericCommand or a shared helper it calls, not a different command's WRONGTYPE check.

**Purpose(驗證目的)**: 題庫廣度,較簡單版本,對照題。
