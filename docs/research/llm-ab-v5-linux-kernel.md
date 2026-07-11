# R4 驗收 v5:Linux kernel 四工具對決——索引可行性、速度實測、N=3(20 題 × 4 臂 × 3 reps)

> **TL;DR**:把戰場從 wpa/redis(~600-900 檔)搬到 Linux kernel v6.6。
> **第一戰(全樹 56,934 C/H 檔,8GB RAM 機器):三個圖工具全部陣亡**——
> cbm 647s 記憶體爆炸(足跡 26.3GB)、codegraph 3,144s Node.js heap OOM、
> ccodegraph 唯一存活但超過 4h 上限(14.5h 時仍在跑,使用者裁決終止)。
> **第二戰(8,170 檔子樹,涵蓋全部 20 題範圍)**:cbm 索引 23.9s、codegraph
> 88.6s、ccodegraph 11,718s(3h15m)——快慢差 490×,但記憶體剖面相反
> (ccodegraph 峰值 RSS 僅 0.51GB,是唯一在全樹撐最久的)。
> **QA 對決(20 題 × 4 臂 × N=3 = 240 次 headless,Sonnet 5,codex 獨立評分)**:
> 中位數總分 none **58**/60、三個圖工具全部 **59**/60;每次查詢 wall 中位數
> none 38.8s < ccodegraph 41.0s < codegraph 46.2s < cbm 52.2s;成本
> none $11.92 < ccodegraph $13.35 < cbm $14.28 ≈ codegraph $14.31。
> **N=3 首次量化了答案穩定性:60 組 (題,臂) 中零組出現 ≥2 分的跨 rep 變異**。
> Token 熱點:ccodegraph 是最省的工具臂(甚至比純 grep 臂還省 17%),
> v4 的教學紀律在 kernel 規模保持有效(`--help` 0 次;codegraph 的 agent
> 則跑了 14 次 `--help`、其 `query` verb 一項就回傳 192KB)。
> **下一步已定案(§12)**:D17 spike——cscope 常駐行程消滅逐符號
> subprocess(timebox 兩天、驗收「邊數零回歸 + 子樹 <30min」、失敗改試
> 直接解析 cscope.out);同時凍結所有其他工程投入,直到取得 ≥10 條真實
> 使用者反饋——五輪 benchmark 的最大戰略警告是「QA 優勢正在縮小,
> 最可轉移的資產可能是 token 紀律教學層與 benchmark 方法論本身」。

本報告獨立完整:附錄 A 含 20 題原文、GT 要點、逐 rep 分數與時間;附錄 B 含
codex 判定 prompt 模板。原始數據在 `hard-benchmark/kernel/`(題庫、20 份 GT、
240 份執行 JSON、60 份評分 JSON、索引 log、分析產物)。

## 目錄

1. [方法論](#1-方法論)
2. [第一戰:全 kernel 索引可行性(三工具全滅)](#2-第一戰全-kernel-索引可行性三工具全滅)
3. [子樹轉進與 GT 重驗](#3-子樹轉進與-gt-重驗)
4. [第二戰:子樹索引計時](#4-第二戰子樹索引計時)
5. [QA 對決:分數(N=3)](#5-qa-對決分數n3)
6. [QA 對決:速度與成本](#6-qa-對決速度與成本)
7. [Token 熱點(kernel 規模)](#7-token-熱點kernel-規模)
8. [codex 評分異常檢查](#8-codex-評分異常檢查)
9. [與 v3/v4(wpa/redis 規模)的對照](#9-與-v3v4-wparedis-規模的對照)
10. [誠實結論](#10-誠實結論)
11. [限制](#11-限制)
12. [下一步:D17 spike 計畫與戰略警告](#12-下一步d17-spike-計畫與戰略警告2026-07-11-智囊團辯論定案)
13. [附錄 A:20 題逐題完整資料](#附錄-a20-題逐題完整資料)
14. [附錄 B:codex 判定 prompt 模板](#附錄-bcodex-判定-prompt-模板)

## 1. 方法論

- **題庫**:20 題(10 類 × 2),改寫自
  `linux-kernel-navigation-benchmark` 參考題庫(80 題),v2-v4 的 GT 教訓
  全部寫進改寫規範(範圍限定詞寫死、decl≠def、雙閘控、模糊詞改可枚舉、
  陷阱明示)。20 個 GT 由平行 agent 對真實 v6.6 源碼建構,每個都要求兩種
  獨立方法交叉驗證;**每一個 agent 都找到至少一項非顯而易見的驗證事實**
  (詳見 §附錄 A 與 gt_LKQ-XXX.md),包括推翻我自己出題假設的三例
  (v6.6 沒有 `x64_sys_call`;`PREEMPT` 經由 `PREEMPT_BUILD` 間接 select
  `PREEMPTION`;random.c 在 v5.18 後已無 `copy_from_user`)。
- **四臂**:none(純 grep)/ ccodegraph / codegraph / cbm。prompt 模板與
  v3/v4 一字不差。**no-build**:不跑 `make defconfig`,ccodegraph 用合成
  compile DB、不跑 clink;cbm/codegraph 本來就 zero-build。
- **N=3**:每題每臂 3 次,執行順序 題→rep→臂(臂最內圈,公平分攤 API
  延遲漂移),**嚴格循序、絕不平行**(計時純度)。
- **計時**(回答使用者「用 time 指令?」):agent 作答時間用 harness 內建
  wall-clock(`time.time()` 包 subprocess,等價 shell `time` 但逐筆進
  JSON),同時記錄 claude CLI 的 `duration_ms`/`duration_api_ms`(分離 API
  延遲);索引計時用 `/usr/bin/time -l`(wall + 峰值 RSS)。
- **評分**:codex(OpenAI CLI,非 Claude)4-slot prompt 對每個 (題, rep)
  獨立評分,共 60 次;`--output-schema` 強制結構化。
- **機器**:8GB RAM 的 macBook(Apple Silicon),執行期間無其他重載。
  過程中遭遇一次訂閱 5 小時用量上限(429),168 筆瞬時失敗——全部清除後
  於重置點後重跑,最終 240/240 rc=0,失敗紀錄不混入數據。

## 2. 第一戰:全 kernel 索引可行性(三工具全滅)

全樹 = v6.6、56,934 個 C/H 檔、1.4GB。上限 4 小時(使用者核定),超時/
崩潰記 DNF。結果:**沒有任何一個圖工具在這台 8GB 機器上完成全 kernel 索引**。

| 工具 | 結局 | 細節 |
|---|---|---|
| cbm | **DNF(崩潰)** | 647s,extraction 進度 28,070/76,683(36%)時被系統終止;峰值記憶體足跡 **26.3GB**(RSS 862MB + 大量壓縮/交換,970 萬次 page reclaim);索引產出 0B |
| codegraph | **DNF(OOM)** | 3,144s(52.4 分);解析階段跑完(100%)後在 ref-resolution/寫入階段撞 **Node.js 2GB heap 上限**(`FATAL ERROR: Reached heap limit`);遺留 3.0GB 不完整索引 |
| ccodegraph | **DNF(超時)** | 唯一存活者:cscope 交叉索引(952MB)在 ~40 分建完,隨後的逐符號查詢迴圈太慢——**4h 上限時仍在跑,使用者裁決在 14.5h 終止**(當時仍在小寫 `ad*` 符號段,依 ASCII 序推估 ~35-40%);部分圖 2.3GB。外推總時間 30-40h |

三種死法互異且都有結構性原因:cbm 把整個 repo 的抽取物堆在記憶體
(footprint 26GB);codegraph 受 Node.js 預設 heap 限制(未調 `NODE_OPTIONS`
——本輪維持 out-of-box 原則,救援嘗試因後續轉進子樹而未執行);ccodegraph
記憶體極省(峰值 <1GB)但**逐符號 subprocess 呼叫 cscope** 的架構讓查詢
次數 × 單次成本在 57k 檔規模爆炸——這是 ccodegraph 的頭號規模化瓶頸,
列入未來工作(batch 查詢/常駐 cscope 行程)。

## 3. 子樹轉進與 GT 重驗

使用者裁決:殺掉全樹 build,改用**8,170 檔子樹**(7,626 C/H)重建四臂公平
對決。子樹組成:`kernel/`、`fs/`(根層 .c/.h + ext4/)、`net/core/`(+
net/Kconfig,Makefile)、`include/`、`arch/x86/`(entry/ + include/)、
`drivers/char/`、e1000e(+ 完整 build 鏈檔案:各層 Makefile/Kconfig、
drivers/pci/Kconfig、drivers/ptp/Kconfig)、`scripts/`、`tools/include/`
——涵蓋全部 20 題的範圍限定詞。

**樹域 GT 事實重驗**(換樹會改變「全樹唯一性」類事實):copy_process 定義
唯一性、vfs_read 宣告唯一性不變;`container_of` 的「其他副本」從全樹 9 個
變成子樹 4 個(SUBTREE ADDENDUM 記入 gt_LKQ-006);e1000 legacy driver
混淆陷阱因該目錄不在子樹而消失(gt_LKQ-035)。四份受影響的 GT 都加了
附註,`questions-kernel.jsonl` 每題加 `execution_tree` 欄位。

## 4. 第二戰:子樹索引計時

同一台機器、同一份子樹、循序執行、`/usr/bin/time -l`:

| 工具 | 索引時間 | 峰值 RSS | 產出規模 | 對 cbm 倍數 |
|---|---|---|---|---|
| none | 0s | — | 無索引 | — |
| cbm | **23.9s** | 1.93GB(足跡 5.1GB) | 520,743 節點 / 714,610 邊 | 1× |
| codegraph | **88.6s** | 1.08GB | 173,483 節點 / 332,805 邊(7,664 檔,6 檔解析失敗) | 3.7× |
| ccodegraph | **11,718s(3h15m)** | **0.51GB** | 426,544 節點 / 336,967 邊(calls 135,471、expands 128,712、includes 39,605、reads 20,253、fnptr 5,518、callback 3,994、writes 3,414) | **490×** |

速度/記憶體的取捨完全反向:cbm/codegraph 快但吃記憶體(正是全樹陣亡的
原因);ccodegraph 慢 2-3 個數量級但記憶體剖面平坦(全樹戰唯一存活到被
人為終止的)。註:cbm/codegraph 的時間為單次量測(<10 分鐘工具原計劃跑
3 次,因整體時程已因全樹戰延宕 1.5 天而從簡,誠實記為 N=1);ccodegraph
3h15m 無重複(N=1)。

## 5. QA 對決:分數(N=3)

codex 獨立評分,每題每臂取 3 reps 中位數(滿分 60):

| Arm | 中位數總分 /60 | 三 reps 總和 /180 |
|---|---|---|
| none(grep) | **58** | 172 |
| ccodegraph | **59** | 172 |
| codegraph | **59** | 174 |
| cbm | **59** | 173 |

- **三個圖工具全部 +1 領先 grep,彼此完全打平**——與 v3(wpa/redis,
  58/58/57 vs 54)方向一致但差距更小:kernel 題目的目錄範圍限定讓 grep
  臂的搜尋空間可控,拉近了差距。
- 逐題分佈(完整見附錄 A):20 題中 17 題全臂中位數同分;真正分化的是
  LKQ-049(build 鏈:ccodegraph 三 reps 全 2——物件數算錯+把 Kconfig 層
  誤述為 Makefile 層;codegraph 全 3)、LKQ-066(get/put 配對:none 三 reps
  全 2——連續三次踩中「grep -c 把定義行算進呼叫數」的 GT 陷阱,答 7 而
  非 6;三個圖工具全 3,pair 級去重直接避開)、LKQ-025/069(cbm/codegraph
  各有一題 2)。
- **N=3 的首個量化結論:答案高度穩定**——60 組 (題,臂) 中**零組**出現
  跨 rep 範圍 ≥2 分;±1 分的閃爍 8 組(單一 rep 偶發的細節遺漏),中位數
  聚合全部吸收。v2-v4 一直掛在限制欄的「N=1 變異數疑慮」,在這類
  有紀律的題目上實測比想像小得多。

## 6. QA 對決:速度與成本

每次查詢 wall 時間(60 runs/臂):

| Arm | 中位數 | 平均 | 最小-最大 | 60 次總計 | API 時間中位 | 總成本 |
|---|---|---|---|---|---|---|
| none | **38.8s** | 48.7s | 17.0-159.4s | 48.7min | 36.0s | **$11.92** |
| ccodegraph | 41.0s | 51.9s | 16.6-165.6s | 51.9min | 40.1s | $13.35 |
| codegraph | 46.2s | 55.0s | 20.9-138.2s | 55.0min | 45.0s | $14.31 |
| cbm | 52.2s | 60.2s | 26.6-131.8s | 60.2min | 50.2s | $14.28 |

- 純 grep 最快(20 題中 8 題最快),但差距不大(中位數差 2-13s);
  ccodegraph 是最快的圖工具臂。wall 與 API 時間中位數幾乎同步(wall −
  api ≈ 2-3s),代表本地開銷小、時間主要花在模型推理與工具往返。
- **每分正確性成本**(中位數分):none $0.206、ccodegraph $0.226、
  codegraph $0.243、cbm $0.242——grep 仍是最省,但 ccodegraph 相對其他
  圖工具最省,延續 v4 的改善(v3 時 ccodegraph 是最貴)。
- **索引攤提**:cbm/codegraph 的索引 24s/89s 在一次會話內就攤平;
  ccodegraph 的 3h15m 需要重複使用才划算——以每查詢省 5-11s(vs
  codegraph/cbm)計,約需上千次查詢;它真正的價值主張在 §7 的 token
  面與記憶體受限環境。

## 7. Token 熱點(kernel 規模)

240 份 transcript 的 tool_result 位元組分佈(每臂 60 runs):

| Arm | 呼叫數 | tool_result 總量 | 最大貢獻者 |
|---|---|---|---|
| none | 396 | 473,767B | Read 219,610B(95 次)、grep 109,323B(151 次) |
| **ccodegraph** | 428 | **393,922B(最省)** | Read 179,016B、grep 72,863B、explore 41,146B(23 次)、sql 38,927B(65 次) |
| codegraph | 490 | **788,798B(最肥)** | Read 223,115B、**query 191,962B(49 次,平均 3.9KB)**、grep 105,179B、**--help 44,596B(14 次)** |
| cbm | 492 | 539,668B | Read 190,178B、query_graph 128,983B(137 次)、grep 95,707B |

- **ccodegraph 臂比純 grep 臂還省 17%**——v4 的 D16 截斷 + SKILL 紀律在
  kernel 規模保持有效:`--help`/`schema`/`status` 全部 0 次、sql 65 次
  平均只有 599B(LIMIT 紀律)、grep 用量比 none 臂少 21%(圖先定位、
  窄讀驗證的模式成立)。
- codegraph 重演了 v3 時 ccodegraph 的病:agent 跑了 14 次 `--help`
  (44.6KB)、`query` verb 無截斷單次平均 3.9KB——**「教學內嵌 + 顯式
  截斷」不是 ccodegraph 特有的需求,是這類工具的通用課題**。
- kernel 規模的假設驗證:「大 repo 會放大圖工具優勢」**部分成立**——
  none 臂的 grep 需要更多次(151 vs ccodegraph 的 119)且單次更肥
  (724B vs 612B),但目錄範圍限定讓差距溫和;真正被放大的是
  **輸出紀律的差距**(codegraph 的 788KB vs ccodegraph 的 394KB,2 倍)。

## 8. codex 評分異常檢查

1. **程式化矛盾掃描**(60 份 × 4 slot):3 筆命中全部是啟發式誤報
   (justification 裡的「no fabricated random.c sites」含 'fabricat' 字根,
   實為讚美句)。真矛盾 0 筆。
2. **跨 rep 一致性**(N=3 新維度):零組 ≥2 分變異;±1 閃爍 8 組,人工
   抽讀後全部是「該 rep 答案真的少了一個細節」,不是評分者噪音——kernel
   輪的 codex 評分穩定度高於 v4(v4 錨定重測有 6/66 漂移)。
3. **抓到一個真異常並修正**:LKQ-006 首輪評分全臂一致 2 分,理由是
   「只列出 4 個副本,漏了 GT 要求的 9 個」——但 9 個是**全樹**事實,
   執行樹(子樹)內就只有 4 個,agents 全部答對了。根因是我的評分腳本把
   GT 檔截斷在 7000 字元,**檔尾的 SUBTREE ADDENDUM 被切掉**,codex 看不到
   子樹修正。修法:把 ADDENDUM 抽出前置後重評——全臂中位數 2→3。這是
   v3 WRQ-002(codex 信了錯的 GT)的變奏:**這次 GT 本身是對的,是餵給
   評分者的 GT 視圖不完整**;教訓寫入評分腳本(addendum 前置)。

## 9. 與 v3/v4(wpa/redis 規模)的對照

| 維度 | v3/v4(wpa 620 檔/redis ~900 檔) | v5(kernel 子樹 8,170 檔;全樹 56,934 檔) |
|---|---|---|
| 索引可行性 | 全工具數秒-數分鐘完成 | 全樹:三工具全滅;子樹:24s / 89s / 3h15m |
| 正確性差距 | v3:圖工具 +3~4 分(/66);v4:ccodegraph 62 vs none 54 | 圖工具 +1(/60),三工具打平 |
| 每查詢時間 | 未系統性量測(v3/v4 焦點在 token) | none 38.8s < ccodegraph 41.0s < codegraph 46.2s < cbm 52.2s |
| token 紀律 | v4 改善後 ccodegraph 最省圖工具 | **ccodegraph 比 grep 臂還省**;codegraph 重演 v3 病 |
| N | 1 | **3**(跨 rep 零高變異) |

規模放大的真相比理論細膩:**索引可行性才是 kernel 規模的第一道生死線**
(理論上圖工具在大 repo 查詢優勢更大,但先要能把索引建出來);建得出來
之後,查詢層的差距主要體現在 token 紀律而非正確性(有紀律的 grep 臂在
目錄範圍明確的題目上幾乎不輸)。

## 10. 誠實結論

1. **全 kernel(57k 檔)+ 8GB RAM = 現階段沒有任何受測圖工具可用**。
   三種死法三種病:記憶體堆積(cbm)、runtime heap 上限(codegraph)、
   逐符號 subprocess 的時間爆炸(ccodegraph)。任何「在 kernel 上用圖
   工具」的宣稱都必須先回答索引怎麼建。
2. **ccodegraph 的規模化瓶頸被精確定位**:cscope 交叉索引本身 40 分鐘
   可接受,爆炸的是 ~50 萬次 `cscope -dL3` subprocess 呼叫。未來工作
   明確:batch 查詢、常駐行程、或 line-oriented 一次掃描(不動 schema,
   只動 L1 填充器)。
3. **QA 層:圖工具在 kernel 題上小勝但不再懸殊**(+1/60,三工具打平)。
   grep 臂最快最省;ccodegraph 是圖工具中時間、成本、token 三項最優,
   v4 的紀律改善在新戰場保持有效且**token 甚至優於 grep 臂**。
4. **N=3 實測回答了 v2 以來的懸念**:這類有 GT 紀律的題目上,單次執行的
   分數波動遠小於担憂(零組 ≥2 分變異),N=1 先導結論的方向可信;但
   ±1 閃爍確實存在(8/60 組),單題結論仍需重複取樣。
5. **評分管線的第三課**:v3 教「GT 可能錯」,v4 教「評分者會信錯的 GT」,
   v5 教「**GT 對、評分者也對,但餵給評分者的 GT 視圖可能被工程細節
   (截斷)弄殘**」——評分基礎設施本身需要驗證(這次靠「全臂一致異常
   扣分」的模式嗅出來的)。

## 11. 限制

- 子樹(8,170 檔)不等於全 kernel:QA 結論的「kernel 規模」宣稱要打折;
  全樹結論只有索引可行性部分(那部分是真全樹)。
- 索引計時 N=1(cbm/codegraph 原計劃 3 次,因全樹戰延宕從簡);
  ccodegraph 的 3h15m 也是單次。
- codegraph 的 Node heap 救援嘗試(`NODE_OPTIONS=--max-old-space-size`)
  與 cbm 重試最終未執行(轉進子樹後兩者都成功,救援失去對照意義;
  全樹救援留給未來)。
- 429 用量上限中斷過一次矩陣執行(168 筆瞬時失敗),已全部清除重跑,
  但重跑批次與原批次相隔 ~1.5h,API 延遲漂移可能有微小影響(N=3 中位數
  緩解)。
- codex 評分單一模型單次判定(同 v3/v4);LKQ-006 事件顯示評分管線
  自身的工程缺陷也是誤差來源。

## 12. 下一步:D17 spike 計畫與戰略警告(2026-07-11 智囊團辯論定案)

v5 收尾後對「下一步」做了一輪刻意的多視角對抗辯論(反駁/本質追問/
擴張/外部視角/執行收斂),結論分「立即行動」與「戰略警告」兩層,
如實記錄於此。

### 12.1 立即行動:D17 spike(timebox 兩天,驗收數字寫死)

**目標**:消滅 §2 定位的頭號規模瓶頸——逐符號 `cscope -dL3` subprocess
呼叫(kernel 級 ~50 萬次 spawn × 952MB 索引掃描 = 3h15m/子樹、外推
30-40h/全樹)。

- **Day 1**:改 `cscope_lines()` 為 **cscope line-mode 常駐行程池**
  (`cscope -dl`,索引載入一次,stdin/stdout 餵查詢取代 per-symbol
  spawn)。驗收標準:①wpa/redis regression fixture **邊數零回歸**
  (測試現成);②kernel 子樹重建 **< 30 分鐘**(現 3h15m,≥6.5×)。
  達標即記 D17、commit。
- **Day 2(條件觸發)**:Day 1 未達標 → 改試**直接解析 `cscope.out`**
  (952MB 交叉索引 40 分鐘就建好了,答案全在裡面;一次線性掃描取代
  50 萬次查詢,格式半公開)。同樣 timebox 一天。
- **兩個 spike 都失敗** → 誠實記錄「cscope 架構到頂」,凍結 L1 引擎
  投入,不再加碼。
- **Day 3**:只重跑索引計時(子樹 + 全 kernel 各一次)更新 §4 表格;
  **QA 不重跑**(+1/60 的分數結論不會因索引變快而改變)。

**冰箱清單**(明文凍結,解凍條件 = D17 有結果 **且** 12.2 的使用者
問題有答案):Rust 重寫(R6)、新邊類型(struct-literal/#ifdef 函式
層級建模)、MCP server、tree-sitter 前端混血。

### 12.2 戰略警告(比行動本身重要)

1. **「索引速度是興趣問題,『誰需要這個工具』是生存問題。」**
   五輪 benchmark、零個真實使用者訪談。D17 之後的第一個戰略動作應該
   是把本報告投放到真實社群收集 ≥10 條外部反饋,用外部訊號而非第六輪
   內部 benchmark 決定 v6 方向。
2. **QA 優勢隨題型波動且正在縮小**(v3 +4/66 → v5 +1/60):隱含假設
   「圖查詢的邊際價值隨 repo 規模成長」在 v5 受到第一次實測打擊——
   規模上去了,有紀律的 grep 幾乎追平。這個假設若不成立,整條產品線
   的地基要重新評估。
3. **本專案最可轉移的資產可能不是圖引擎**:(a)token 紀律教學層
   (v4 -32%、v5 中 ccodegraph 臂比 grep 臂還省 17%,而 codegraph 在
   v5 重演了我們 v3 的全部病徵——證明紀律層是跨工具的通用缺口);
   (b)benchmark 方法論本身(42 份 GT、三課評分教訓:GT 會錯/評分者
   會信錯的 GT/評分者看到的 GT 視圖會被工程細節弄殘)。兩者都可獨立
   於 ccodegraph 發布。
4. **身分問題**:ccodegraph 目前是「cscope 的 agent 介面 + 誠實標注
   層」,其上限與病灶(D15、本輪的逐符號迴圈)都繼承自 cscope。
   D17 若走到「直接解析 cscope.out」那一步,實質上已開始換引擎——
   屆時應正面回答「站在 cscope 上,還是自立門戶」。

## 附錄 A:20 題逐題完整資料

每題含:題目原文、改寫理由、GT 要點(完整版見 `kernel/gt_LKQ-XXX.md`)、
四臂 × 3 reps 分數與 wall 時間中位數。

### LKQ-001 [symbol-definition/L1](原題 LKQ-001)

**題目原文(verbatim)**:Find the definition of copy_process() (the function body, not any declaration or comment mention). Return the file path, the line number where the definition starts, and the full signature including return type, storage class/attributes, and all parameters. State explicitly whether the function is static.

**改寫理由**:原題已具體;加上「非宣告非註解」與 static 判定(decl/def 陷阱教訓)。

**GT 要點**(完整版 `gt_LKQ-001.md`):VERIFIED. kernel/fork.c:2240, `__latent_entropy struct task_struct *copy_process(struct pid *pid, int trace, int node, struct kernel_clone_args *args)` (params 2241-2244), NOT static (declared include/linux/sched/task.h:95). Unique in tree; confusables rcu_copy_process/klp_copy_process documented. Rubric: 3 = file+line(±2)+full signature incl __latent_entropy+not-static; staticness unaddressed caps at 1. Full GT: gt_LKQ-001.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,21s) | ccodegraph 3,3,3(中位 3 分,22s) | codegraph 3,3,3(中位 3 分,21s) | cbm 3,3,3(中位 3 分,50s)

### LKQ-006 [symbol-definition/L2](原題 LKQ-006)

**題目原文(verbatim)**:Find the definition of the container_of macro that kernel code actually uses (not copies under tools/ or scripts/). Return the file path and line number, quote the full macro body, and explain its three parameters. Also report whether OTHER definitions of container_of exist elsewhere in the tree (e.g. under tools/) and why they do not conflict with the kernel one.

**改寫理由**:加入同名多定義的消歧要求(v3 WRQ-002 hiredis 教訓:真實的符號碰撞必須被正確辨識而非扣分)。

**GT 要點**(完整版 `gt_LKQ-006.md`):VERIFIED. Primary: include/linux/container_of.h:18 (body 18-23, static_assert + offsetof form); kernel.h merely includes it. Exactly 10 `#define container_of` tree-wide: 9 non-kernel copies (5 tools/, 2 scripts/, radeon mkregtable.c hostprog, samples/bpf) — separate build domains, no conflict. Rubric: tools/-copy-as-primary scores low; reporting copies = credit. Full GT: gt_LKQ-006.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,36s) | ccodegraph 3,3,3(中位 3 分,40s) | codegraph 3,3,2(中位 3 分,40s) | cbm 3,3,3(中位 3 分,51s)

### LKQ-014 [references-usages/L2](原題 LKQ-014)

**題目原文(verbatim)**:List every use of EXPORT_SYMBOL_GPL in .c files under kernel/sched/ (that subtree only). Return the exported symbol name and file:line for each, and state the exact total count. Cross-check your total with an independent counting method before answering.

**改寫理由**:原題已可枚舉;加上明確總數 + 交叉核對要求(「列表對、加總錯」通病的防線)。

**GT 要點**(完整版 `gt_LKQ-014.md`):VERIFIED. Exact textual total=53 EXPORT_SYMBOL_GPL( in kernel/sched/*.c (per-file: core.c 18, wait.c 7, cputime.c 6, isolation.c 6, clock.c 5, wait_bit.c 3, cpufreq.c 2, psi.c 2, topology.c 2, fair.c 1, idle.c 1). Macro trap: core.c:8875 PREEMPT_MODEL_ACCESSOR instantiated 3x → 55 with that reasoning also correct. Plain EXPORT_SYMBOL=72 (distractor; ~72/125 answers = wrong macro, score 1). Full GT: gt_LKQ-014.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,49s) | ccodegraph 3,3,3(中位 3 分,76s) | codegraph 3,3,3(中位 3 分,60s) | cbm 3,3,3(中位 3 分,98s)

### LKQ-011 [references-usages/L2](原題 LKQ-011)

**題目原文(verbatim)**:Find every call to copy_from_user() in exactly two files: drivers/char/mem.c and drivers/char/random.c. For each call site give file:line, the enclosing function, and the destination buffer expression. State the exact per-file totals. Exclude comments and any *_copy_from_user variants.

**改寫理由**:原題範圍模糊(under drivers/char/ + classify where possible)→ 收斂到兩個具名檔案、明確排除變體。

**GT 要點**(完整版 `gt_LKQ-011.md`):VERIFIED + QUESTION TRAP CONFIRMED. mem.c total=1 (line 242, write_mem(), dest `ptr`); random.c total=**0** (v5.18+ uses iov_iter: copy_from_iter at random.c:1410). Correct answers MUST affirmatively report random.c=0; invented random.c sites score 0-1. Zero excluded-variant hits in either file. Full GT: gt_LKQ-011.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,33s) | ccodegraph 3,3,3(中位 3 分,29s) | codegraph 3,3,3(中位 3 分,46s) | cbm 3,3,3(中位 3 分,91s)

### LKQ-017 [caller-callee/L2](原題 LKQ-017)

**題目原文(verbatim)**:List every direct call to wake_up_process() in .c files under kernel/ (recursive, kernel/ subtree only; exclude comments, strings, and other wake_up_* variants). Return the enclosing caller function and file:line for each call site, plus the exact total number of call sites.

**改寫理由**:原題已好;加排除變體與精確總數要求。

**GT 要點**(完整版 `gt_LKQ-017.md`):VERIFIED. Exact total=47 direct call sites (31 files; workqueue.c 5, kthread.c 5). Traps: 48 = included definition core.c:4476 or EXPORT_SYMBOL line; 59 = comments included (11 comment hits). Two methods agree (classified grep vs comment-stripping parser). Rubric: 3 = 47 (46-48 with explicit correct note) + correct enclosing functions. Full GT: gt_LKQ-017.md

**結果(r1,r2,r3 分數;wall 中位)**:none 2,3,3(中位 3 分,156s) | ccodegraph 3,2,3(中位 3 分,128s) | codegraph 3,3,2(中位 3 分,110s) | cbm 3,3,2(中位 3 分,127s)

### LKQ-022 [caller-callee/L2](原題 LKQ-022)

**題目原文(verbatim)**:List every function directly called by ksys_read() (defined in fs/read_write.c), in source order, with the call-site line numbers. If something that looks like a call is a macro, say so and identify what it expands to if determinable from the source.

**改寫理由**:原題已好;加巨集辨識要求。

**GT 要點**(完整版 `gt_LKQ-022.md`):VERIFIED. ksys_read (fs/read_write.c:602-619) makes exactly 4 calls in order: fdget_pos(604, static inline file.h:72), file_ppos(608, file-local static inline :597), vfs_read(613, extern :450), fdput_pos(616, static inline file.h:77). NO macros masquerade as calls (repo-wide #define grep empty) — the macro clause's correct answer is 'none'. f.file / f.file->f_pos=pos (615) are member accesses, not calls. Full GT: gt_LKQ-022.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,29s) | ccodegraph 3,2,3(中位 3 分,30s) | codegraph 3,3,3(中位 3 分,29s) | cbm 3,3,3(中位 3 分,69s)

### LKQ-025 [entry-path/L3](原題 LKQ-025)

**題目原文(verbatim)**:Trace the x86_64 read() system call path from the syscall definition to the VFS helper: start at the SYSCALL_DEFINE3(read, ...) site (file:line) and name every named function hop in order, with file:line for each, ending at vfs_read(). Also state, from in-tree (non-generated) sources, how the syscall number is mapped to that handler (which table file lists it).

**改寫理由**:指名起點/終點讓路徑可評分;syscall 表指向 in-tree 的 syscall_64.tbl(避開 generated headers)。

**GT 要點**(完整版 `gt_LKQ-025.md`):VERIFIED. Chain (all fs/read_write.c): SYSCALL_DEFINE3(read) :621 → ksys_read :602 → vfs_read :450. Table: arch/x86/entry/syscalls/syscall_64.tbl:11 `0 common read sys_read` (in-tree). Macro mechanism: include/linux/syscalls.h:221/228 + x86 syscall_wrapper.h:228-240 (__x64_sys_read stub). TRAP: x64_sys_call does NOT exist in v6.6 (v6.9+) — wrong hop, penalized. Bonus dispatch refs documented. Full GT: gt_LKQ-025.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,76s) | ccodegraph 3,3,3(中位 3 分,51s) | codegraph 3,3,3(中位 3 分,49s) | cbm 3,2,2(中位 2 分,45s)

### LKQ-027 [entry-path/L3](原題 LKQ-027)

**題目原文(verbatim)**:Trace the paths from the fork and clone syscall definitions (kernel/fork.c) to copy_process(): name each named function hop in order with file:line for both syscalls, and state which shared intermediate helper both paths funnel through.

**改寫理由**:把「trace the syscall path」改成雙路徑+共同漏斗函式的明確要求。

**GT 要點**(完整版 `gt_LKQ-027.md`):VERIFIED. fork: SYSCALL_DEFINE0(fork) fork.c:2991 → kernel_clone(&args) :2998. clone: SYSCALL_DEFINE5/6 variants :3020/3025/3030/3036 → kernel_clone :3052. Funnel = kernel_clone (def :2868) → copy_process call :2909 (def :2240). Guards (__ARCH_WANT_SYS_FORK/CLONE, CONFIG_MMU) precision-only. Stale name trap: _do_fork removed pre-v5.10. Full GT: gt_LKQ-027.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,45s) | ccodegraph 3,3,3(中位 3 分,45s) | codegraph 2,3,3(中位 3 分,73s) | cbm 3,3,3(中位 3 分,40s)

### LKQ-035 [callback-indirect/L3](原題 LKQ-035)

**題目原文(verbatim)**:In the e1000e driver (drivers/net/ethernet/intel/e1000e/): find the struct net_device_ops instance — variable name and file:line; the function assigned to .ndo_start_xmit (name + definition file:line); and the registration path: which function assigns this ops struct to netdev->netdev_ops (file:line).

**改寫理由**:加上註冊路徑要求(fnptr 註冊點驗證是 v2 以來的拿分紀律)。

**GT 要點**(完整版 `gt_LKQ-035.md`):VERIFIED. e1000e_netdev_ops netdev.c:7327 (static const); .ndo_start_xmit=e1000_xmit_frame :7330, defined :5781; registration `netdev->netdev_ops = &e1000e_netdev_ops;` :7451 inside e1000_probe. Unique ops instance in the directory. Trap: legacy e1000 driver has near-identical names in e1000_main.c — wrong per scope limiter. Full GT: gt_LKQ-035.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,28s) | ccodegraph 3,3,3(中位 3 分,31s) | codegraph 3,3,3(中位 3 分,27s) | cbm 3,3,3(中位 3 分,28s)

### LKQ-033 [callback-indirect/L3](原題 LKQ-033)

**題目原文(verbatim)**:In fs/ext4/file.c find the ext4_file_operations definition (file:line). Map each of these fields to its assigned function and give each function's definition file:line (definitions may live in other ext4 files): .read_iter, .write_iter, .open, .release, .fsync. If any of these five fields is absent from the struct literal, say so explicitly rather than guessing.

**改寫理由**:指名 5 個欄位讓對映可評分;「缺席要明講」防幻覺。

**GT 要點**(完整版 `gt_LKQ-033.md`):VERIFIED. ext4_file_operations fs/ext4/file.c:950-968. ALL FIVE fields present (absent-clause is a distractor): .read_iter=ext4_file_read_iter(file.c:130), .write_iter=ext4_file_write_iter(:703), .open=ext4_file_open(:878), .release=ext4_release_file(:166), .fsync=ext4_sync_file(fs/ext4/fsync.c:129 — sole cross-file; ext4.h:2836 is declaration only, not acceptable as definition site). Full GT: gt_LKQ-033.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,24s) | ccodegraph 3,3,3(中位 3 分,24s) | codegraph 3,3,3(中位 3 分,30s) | cbm 3,3,3(中位 3 分,36s)

### LKQ-046 [data-structure/L2](原題 LKQ-046)

**題目原文(verbatim)**:In struct net_device (include/linux/netdevice.h), identify the field that points to the device operations table (struct net_device_ops): field name + line number inside the struct definition. Then show one real call site in net/core/dev.c where a callback is invoked through this field (file:line + which ndo_* callback).

**改寫理由**:原題已好;invocation 範例限定 net/core/dev.c 讓其可驗證。

**GT 要點**(完整版 `gt_LKQ-046.md`):VERIFIED. Field `netdev_ops` include/linux/netdevice.h:2092 (struct starts 2056; kerneldoc 1835 not the declaration). 19 valid invocation sites in net/core/dev.c (10 direct dev->netdev_ops->ndo_*, 9 via ops alias; e.g. 655 ndo_get_iflink, 3553 ndo_features_check, 1475 ndo_open, 10096 ndo_init). Trap: ops->ndo_start_xmit fires in netdevice.h not dev.c; ndo_do_ioctl in dev_ioctl.c out of scope. Any one valid site = full credit. Full GT: gt_LKQ-046.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,23s) | ccodegraph 3,3,3(中位 3 分,26s) | codegraph 3,3,3(中位 3 分,25s) | cbm 3,3,3(中位 3 分,38s)

### LKQ-043 [data-structure/L3](原題 LKQ-043)

**題目原文(verbatim)**:List every field whose declared type is struct list_head (value fields, not pointers) directly inside the struct task_struct body (include/linux/sched.h). State explicitly how you treated fields inside conditional #ifdef blocks (count them, and say which config they need) and any inside unnamed structs/unions. Give field name + line for each and the exact total. Then show one real list_for_each_entry-family iteration over any one of these lists in kernel/ (file:line).

**改寫理由**:task_struct 有大量 #ifdef 欄位——把 v2 WRQ-013 的條件編譯歸戶教訓直接寫進題目要求。

**GT 要點**(完整版 `gt_LKQ-043.md`):VERIFIED. task_struct body include/linux/sched.h:743-1554. list_head value fields: 7 unconditional (tasks 870, children 989, sibling 990, ptraced 999, ptrace_entry 1000, thread_group 1005, thread_node 1006) + 7 conditional (rcu_node_entry 847 PREEMPT_RCU, rcu_tasks_holdout_list 856 TASKS_RCU, trc_holdout_list 863 + trc_blkd_node 864 TASKS_TRACE_RCU, cg_list 1227 CGROUPS, pi_state_list 1238 FUTEX, perf_event_list 1246 PERF_EVENTS) = 14 total. Zero list_head pointers, zero anonymous unions (presup…

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,49s) | ccodegraph 3,3,3(中位 3 分,60s) | codegraph 3,3,3(中位 3 分,61s) | cbm 3,3,3(中位 3 分,76s)

### LKQ-049 [kconfig-build/L2](原題 LKQ-049)

**題目原文(verbatim)**:For the e1000e driver: (a) the Kconfig option that enables it — file:line of the config declaration; (b) the Makefile rule(s) compiling its objects — file:line of the obj-$(CONFIG_...) line and the object list; (c) explicitly enumerate ALL build-system gating layers: the driver-local Makefile line AND every parent-directory Makefile/Kconfig condition required for the build system to even descend into that directory (e.g. vendor-level config).

**改寫理由**:雙(多)閘控是 v2-v4 反覆出現的教訓(Makefile 檔案級閘控),kernel 的巢狀目錄下降讓它更立體。

**GT 要點**(完整版 `gt_LKQ-049.md`):VERIFIED. (a) config E1000E drivers/net/ethernet/intel/Kconfig:58 (depends PCI :60, PTP_1588_CLOCK_OPTIONAL :61, select CRC32 :62, inside if NET_VENDOR_INTEL 17-359). (b) e1000e/Makefile:11 obj-$(CONFIG_E1000E)+=e1000e.o, objs 13-15 (11 objects). (c) Layers: intel/Makefile:8, ethernet/Makefile:50 (NET_VENDOR_INTEL), net/Makefile:52 (ETHERNET), drivers/Makefile:95 **obj-y += net/ (UNCONDITIONAL — key trap: NETDEVICES/NET gate only via Kconfig, never Makefile)**, Kbuild:94 obj-y += drivers/. Kconf…

**結果(r1,r2,r3 分數;wall 中位)**:none 2,3,2(中位 2 分,60s) | ccodegraph 2,2,2(中位 2 分,79s) | codegraph 3,3,3(中位 3 分,105s) | cbm 2,3,3(中位 3 分,81s)

### LKQ-053 [kconfig-build/L3](原題 LKQ-053)

**題目原文(verbatim)**:Locate where preempt_schedule() (kernel/sched/core.c) is conditionally compiled: quote the exact preprocessor guard around its definition (file:line), name the CONFIG symbol used, and find where that symbol is declared in Kconfig (file:line). If the guard symbol differs from CONFIG_PREEMPT itself (e.g. CONFIG_PREEMPTION), explain the relationship between the two per the Kconfig declarations.

**改寫理由**:CONFIG_PREEMPT vs CONFIG_PREEMPTION 的區分是典型「靠記憶會答錯、靠源碼才對」的題。

**GT 要點**(完整版 `gt_LKQ-053.md`):VERIFIED + STALE-KNOWLEDGE TRAP STRONGER THAN EXPECTED. Guard: #ifdef CONFIG_PREEMPTION kernel/sched/core.c:6875 (preempt_schedule def :6880, endif :6987). config PREEMPTION kernel/Kconfig.preempt:92; config PREEMPT :51. In v6.6 PREEMPT does NOT directly select PREEMPTION — it selects PREEMPT_BUILD (:54), which selects PREEMPTION (:11); only PREEMPT_RT selects it directly (:73). Direct-select claims score 2; CONFIG_PREEMPT-as-guard scores ≤1. Full GT: gt_LKQ-053.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,46s) | ccodegraph 2,3,3(中位 3 分,50s) | codegraph 3,2,3(中位 3 分,59s) | cbm 2,3,3(中位 3 分,46s)

### LKQ-060 [include-dependency/L2](原題 LKQ-060)

**題目原文(verbatim)**:For vfs_read: give (a) the header file:line where it is DECLARED (prototype), and (b) the file:line where it is DEFINED (function body). Label which is which explicitly, and name the header a typical caller includes to obtain the declaration. If the declaration is NOT in a public header (e.g. it lives in an fs-internal header), report that accurately instead of assuming linux/fs.h.

**改寫理由**:decl/def 陷阱 + v6.6 實況(vfs_read 的宣告位置可能不在多數人以為的 fs.h)——防記憶答題。

**GT 要點**(完整版 `gt_LKQ-060.md`):VERIFIED + VERSION TRAP. In v6.6 the vfs_read prototype is in the PUBLIC header include/linux/fs.h:1964 (fs/internal.h has NO vfs_read — that move is later kernels; the question's internal.h hint is a trap FOR THIS VERSION). Definition fs/read_write.c:450 (body 450-479). NOT EXPORT_SYMBOL'd (module-unavailable; exported alternative kernel_read at :448). fs/internal.h claims score ≤1. Full GT: gt_LKQ-060.md

**結果(r1,r2,r3 分數;wall 中位)**:none 2,3,3(中位 3 分,31s) | ccodegraph 3,3,3(中位 3 分,30s) | codegraph 3,3,3(中位 3 分,38s) | cbm 3,3,3(中位 3 分,30s)

### LKQ-057 [include-dependency/L2](原題 LKQ-057)

**題目原文(verbatim)**:Find the header defining struct sk_buff (file + line of the struct definition). Then count the .c files directly under net/core/ (that single directory, not recursive) that directly #include that header by any spelling, list them, and give the exact count. Cross-check the count with a second method.

**改寫理由**:限定單一目錄讓枚舉可評分;拼寫變體+交叉核對是 v3 WRQ-015 的教訓。

**GT 要點**(完整版 `gt_LKQ-057.md`):VERIFIED. struct sk_buff { at include/linux/skbuff.h:842 (unique definition). net/core/ has 56 .c files (non-recursive); exactly **21** directly include <linux/skbuff.h> (list in GT; no alternate spellings exist here). 35 transitive-only (gro.c via net/gro.h, neighbour.c via netdevice.h etc.). Rubric: 3 = header+exact 21+list; 19-23 = 2; recursive/transitive counting = 1. Full GT: gt_LKQ-057.md

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,27s) | ccodegraph 3,3,3(中位 3 分,42s) | codegraph 3,3,3(中位 3 分,38s) | cbm 3,3,3(中位 3 分,71s)

### LKQ-066 [dataflow-lifetime/L3](原題 LKQ-066)

**題目原文(verbatim)**:In kernel/exit.c, list every call site of put_task_struct() (file:line + enclosing function, exact total). Then, for ONE of those sites, trace and show the matching reference acquisition (the get_task_struct() or documented initial reference it releases), with file:line evidence — i.e., demonstrate one complete acquire/release pairing rather than asserting it.

**改寫理由**:把 representative pairing 改成「枚舉全部 put + 驗證一組配對」的可評分結構。

**GT 要點**(完整版 `gt_LKQ-066.md`):VERIFIED. Exact total=6 put_task_struct call sites in kernel/exit.c: 226 (delayed_put_task_struct), 521+527 (mm_update_next_owner, under CONFIG_MEMCG), 1117 (wait_task_zombie WNOWAIT), 1310 (wait_task_stopped), 1360 (wait_task_continued). Trap: naive grep -c returns 7 (definition line 218 substring); put_task_struct_rcu_user :282 is a different symbol. Primary evidenced pairing: get_task_struct :1303 (kernel's own comment 1296-1302) → put :1310 in wait_task_stopped; alternates documented incl. t…

**結果(r1,r2,r3 分數;wall 中位)**:none 2,2,2(中位 2 分,39s) | ccodegraph 3,3,3(中位 3 分,39s) | codegraph 3,3,3(中位 3 分,47s) | cbm 3,3,3(中位 3 分,58s)

### LKQ-069 [dataflow-lifetime/L3](原題 LKQ-069)

**題目原文(verbatim)**:In kernel/params.c (this file only), examine every kmalloc/kzalloc/kmalloc_array call site. For each: file:line, enclosing function, and classify the allocation's fate: (a) freed on an error path in the same function (give the kfree file:line), (b) ownership transferred (say to whom/where), or (c) freed unconditionally in the same function. Do NOT report ownership transfers as leaks.

**改寫理由**:v2 WRQ-017 的「無本地釋放≠洩漏」教訓寫進題目;單檔限定讓枚舉可評分。

**GT 要點**(完整版 `gt_LKQ-069.md`):VERIFIED + QUESTION NOTE: kernel/params.c has 4 sites (1 kmalloc + 3 kzalloc; kmalloc_array named in question has ZERO hits — reportable fact). ALL FOUR are fate (b) ownership transfer; zero (a)/(c) — pure 'no local free ≠ leak' test: :51 kmalloc_parameter→kmalloced_params list (freed via maybe_kfree_parameter :71/param_free_charp :296); :639+:644 add_sysfs_param→mk->mp/grp.attrs (caller cleans via free_module_param_attrs :693-694, in-code contract comment :646); :772 locate_module_kobject→modul…

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,2(中位 3 分,107s) | ccodegraph 2,3,3(中位 3 分,129s) | codegraph 3,2,2(中位 2 分,119s) | cbm 3,2,3(中位 3 分,100s)

### LKQ-073 [locking-rcu/L3](原題 LKQ-073)

**題目原文(verbatim)**:Identify the per-runqueue lock field inside struct rq (kernel/sched/sched.h): field name + line. Give the primary helper functions used to take/release it in v6.6 (names + definition file:line) — report what the source actually shows, which may differ from older kernels' plain spin_lock usage. Then give two real call sites in kernel/sched/core.c that acquire this lock (file:line each).

**改寫理由**:v6.6 的 raw_spin_rq_lock 家族與舊 kernel 記憶不同——防記憶答題,強迫查源碼。

**GT 要點**(完整版 `gt_LKQ-073.md`):VERIFIED + STALE-MEMORY TRAP. Field: raw_spinlock_t __lock at kernel/sched/sched.h:964 (no plain `lock` field exists — double-underscore rename forces accessor use). Helpers: rq_lockp sched.h:1235/1333 (CONFIG_SCHED_CORE dual defs — returns &rq->core->__lock under core sched), __rq_lockp :1243/1338, raw_spin_rq_lock sched.h:1370 (static inline, NOT core.c), raw_spin_rq_lock_nested core.c:551 (retry loop — lock pointer can change under core-sched toggling), raw_spin_rq_trylock core.c:576, raw_spi…

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,50s) | ccodegraph 3,2,3(中位 3 分,51s) | codegraph 3,3,3(中位 3 分,50s) | cbm 3,3,2(中位 3 分,45s)

### LKQ-077 [locking-rcu/L3](原題 LKQ-077)

**題目原文(verbatim)**:Find two distinct call_rcu() call sites, one under kernel/sched/ and one under kernel/rcu/ or kernel/ (top level). For each: file:line, the callback function passed, and the callback's definition file:line. For one of them, state what resource the callback releases.

**改寫理由**:限定子樹+兩例讓題目可評分。

**GT 要點**(完整版 `gt_LKQ-077.md`):VERIFIED. kernel/sched/: 7 call_rcu sites (topology.c:456,465→destroy_perf_domain_rcu:325; :521,534→free_rootdomain:473; :654→destroy_sched_domains_rcu:640; core.c:10380→sched_free_group_rcu:10367; :10435→sched_unregister_group_rcu:10426). kernel/*.c top: 22 sites (fork.c 5, workqueue.c 3, audit* 5-across-3-files w/ cross-file callback auditfilter.c:99, etc.). kernel/rcu/: 3 genuine (rcuscale.c:661,774, update.c:607); traps: tiny.c:170/tree.c:2765 are call_rcu DEFINITIONS not sites. Canonical re…

**結果(r1,r2,r3 分數;wall 中位)**:none 3,3,3(中位 3 分,25s) | ccodegraph 3,3,3(中位 3 分,36s) | codegraph 3,3,3(中位 3 分,44s) | cbm 3,3,3(中位 3 分,47s)



## 附錄 B:codex 判定 prompt 模板

v5 使用的 4-slot 評分 prompt(`kernel/v5-analysis/score_v5.py` 的
`build_prompt`;對每個 (題, rep) 呼叫一次,共 60 次)。與 v3/v4 模板的
差異:開頭加入子樹說明與「honor SUBTREE ADDENDUM」指示;GT 文件的
ADDENDUM 區段抽出前置(LKQ-006 誤評事件後的修正)。

```text
You are an independent grader for a Linux-kernel (v6.6) code-navigation
benchmark. You are NOT the one who built the ground truth or ran the agents —
grade strictly from the evidence below, and be skeptical of confident-sounding
but unverifiable claims. NOTE: the execution tree was an 8,170-file subtree of
v6.6; the GT documents include SUBTREE ADDENDUM sections where tree-scoped
facts differ — honor those addenda over full-tree statements when they exist.

## Question ({qid})
{question}

## Evaluation notes (verified GT summary, includes scoring guidance)
{evaluation_notes}

## Full GT reference document
{gt_document with SUBTREE ADDENDUM hoisted to front, first 7000 chars}

## Four independent AI agents answered this question, each with a different
## tool/no-tool setup. Score EACH one 0-3 against the GT above:
## 0 = wrong/fabricated, 1 = mostly wrong or badly incomplete, 2 = mostly
## correct but with a real gap the GT calls out as a scoring dimension,
## 3 = fully correct per the GT's own scoring rubric.
## Judge each answer independently — do not let one answer's quality anchor
## your judgment of the others. Give a one-to-two sentence justification per
## score, citing what matched or didn't match the GT.

### Answer A (tool="none", grep/read only)
{answer_none, first 4000 chars}

### Answer B (tool="ccodegraph")
{answer_ccodegraph, first 4000 chars}

### Answer C (tool="codegraph", third-party)
{answer_codegraph, first 4000 chars}

### Answer D (tool="cbm", third-party)
{answer_cbm, first 4000 chars}

Return your scores as JSON matching the required schema, using these EXACT
keys for the four answers: "none" (Answer A), "ccodegraph" (Answer B),
"codegraph" (Answer C), "cbm" (Answer D).
```

執行方式:`codex exec --skip-git-repo-check --sandbox read-only
--output-schema <score_schema.json> --output-last-message <out> "<prompt>"`;
schema 強制每臂 `{score: 0-3, justification}`。
