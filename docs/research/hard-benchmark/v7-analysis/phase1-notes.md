# v7 Phase 1 工作筆記(進行中;續作依據)

計畫:`~/git/ccodegraph/docs/research/llm-ab-v7-plan.md`
工作樹:`~/kernel-bench/v7/gate-redis`(build 綠 69.7s)、`gate-wpa`(build 綠 2.9s,config=`v7/wpa-build.config`)
hook:`~/kernel-bench/v7/gate-diag/diag-hook.sh`(已驗證)

## 8 題清單與進度

| # | 族 | repo | 狀態 | 目標 |
|---|---|---|---|---|
| ET-001 | 型別傳播-易 | redis | **定案** | `checkStringLength`(t_string.c static)加第4參數 `int quiet`;GT 站點=t_string.c:604,623,1391(編譯器實測點名)+定義:26;任務=加參數(quiet≠0 時不 addReplyError)+改齊呼叫點傳0+build綠 |
| ET-002 | 型別傳播-難 | wpa | **定案** | `os_get_time`(os.h 宣告+os_unix.c 定義)加第2參數 `int clock_source`;GT=10 站點/9 檔(編譯器點名):ieee802_11_shared.c:440, ieee802_11.c:216, random.c:142, eapol_auth_sm.c:1306, tlsv1_client_write.c:54, x509v3.c:1852, common.c:240, wpa_debug.c:73, notify.c:512, notify.c:528;任務=加參數(0=REALTIME 語意)+改齊+build綠 |
| ET-003 | 注入錯-易 | redis | **定案** | 注入須 error 級(redis switch 多帶 default,-Wswitch 廢);候選:(a) t_string.c 一處 checkStringLength 呼叫 typo 成 checkStrLength → implicit-decl error(b) latency.c 欄位名 .latency 改 .latency_ms → no-member error;診斷點名處=修改處,「易」可接受;patch 待做+驗證 |
| ET-004 | 注入錯-難 | wpa | **定案** | patches/ET-004.patch:5 錯/5 檔(config_file.c:29 typo os_strlength、scan.c:1137 少參數、events.c:132 假欄位 cur_ssid、eloop.c:615 假欄位 time.seconds、wpa.c:103 假欄位 pairwise_ciph);全部 error 級實測 |
| ET-005 | 抽結構-易 | wpa | **定案** | wpa_scan_res 抽 qual+noise → struct {int qual;int noise;} sig;GT=12 站點/3 檔(bss.c:280,281;events.c:1435,1436;scan.c:1701,1712,1784,1785,1792,1793,1872,1878)|
| ET-006 | 抽結構-難 | redis | **定案** | redisServer 抽 stat_numcommands/numconnections/expiredkeys → core_stats 子 struct;GT=17 站點/7 檔(blocked.c:100,cluster.c:288,db.c:2817,networking.c:1633,server.c:1596,2122,2123,2168,2885,2886,2887,4187,6699,6700,6716,t_string.c:170,1311)|
| ET-007 | API遷移-易 | wpa | **定案** | wpa_config_get_line(static,config_file.c)改名 wpa_config_read_line + stream 參數提前;GT=gt/ET-007-sites.txt(定義:64 + 呼叫 178,236,292,400);驗收=build綠+舊名grep=0 |
| ET-008 | API遷移-難 | redis | **定案** | lookupKeyReadOrReply(c,key,reply) 改名 lookupKeyReadOrReplyEx(key,c,reply)(參數對調);GT=gt/ET-008-sites.txt(37 站點/10 檔);驗收=build綠+舊名grep=0 |

## GT 建構法(計畫 §2)

- 型別傳播:在乾淨樹**預先實做該編輯** → `make 2>&1` 收錯誤清單 = GT 受影響站點(編譯器點名);還原樹
- 注入錯:patch 檔固定(`v7/patches/ET-00X.patch`),GT=注入清單
- 抽結構/API遷移:grep+圖雙法數站點清單
- 每題產出:`questions-v7.jsonl` 條目(id/repo/family/難度/task prompt/GT)+ `gt_ET-00X.md` + 驗收腳本 `verify_ET-00X.sh`(輸出 PASS/FAIL + 細項)

## 歸檔位置

`~/git/ccodegraph/docs/research/hard-benchmark/v7/`(questions-v7.jsonl、gt_*.md、patches/、verify/)

## 驗收腳本統一介面

`verify_ET-00X.sh <tree-root>` → stdout 最後一行 `RESULT: PASS|FAIL build=0/1 sites=N/M ...`


## Phase 1 實測教訓(2026-07-19)

0. **改簽名(加參數)是可靠爆診斷路線**:ET-001 實測 3 呼叫點全被 error 點名
1. **擴寬型改動全靜默**:redis latencySample.time int32→int64 參考編輯後
   make 零警告——C 隱式轉換不觸發診斷。型別傳播題必須選「會爆診斷」的
   改法,且 GT 建構前必須實測診斷非空:
   - 函式回傳型別改變 → 函式指標賦值處 error(redis command table!)
   - 欄位 int → 指標/struct → 所有使用處 error
   - printf 直接吃該欄位的檔案(-Wformat)——redis 多用 addReply 家族,
     printf 少,wpa 的 wpa_printf 是巨集(格式檢查?要驗)
2. redis 基線警告數 = 0(乾淨,適合當裁判);增量 make 可用(latency.h
   改動只重編相依 TU,~秒級)
3. gate-redis 樹已還原乾淨(latency.h 復原)

4. **make 必須 -k**(否則遇錯即停只見部分站點);**gate-wpa 非 git repo**(archive 解出),還原只能手動 sed——出題參考編輯一律成對 sed(改/還原)並 grep 驗證

5. **redis 的 enum switch 幾乎都帶 default** → -Wswitch 注入路線廢;注入錯改用 error 級(typo 呼叫/假欄位名/參數不符)
6. 續作順序:ET-003 patch 做+驗 → ET-004(wpa 5 注入,含 typo+假欄位+參數不符+漏原型,分佈 3+ 檔)→ ET-005/006(抽結構,站點=grep 欄位使用點+編譯器)→ ET-007/008(API 遷移,站點=grep)→ 寫 questions-v7.jsonl + gt_ET-*.md + verify_ET-*.sh(統一介面 RESULT: 行)→ 歸檔 repo docs/research/hard-benchmark/v7/ → commit
7. 驗收腳本骨架:cp 樹→apply 題目起始狀態(注入題 apply patch)→(agent 已作答的樹直接驗)make -k 計 error/warning;站點覆蓋:對 GT 清單逐一 grep 新簽名/正確碼;RESULT: PASS/FAIL build=X sites=N/M

8. 全 8 題定案(2026-07-19)。剩:questions-v7.jsonl、gt_ET-*.md、verify_ET-*.sh、歸檔 repo、commit
