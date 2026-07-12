# LLM A/B v6:claude 原生 LSP(clangd + 真實 compile DB)對決(2026-07-12)

> **TL;DR**:外部建議「Claude Code 的 LSP 功能 + compile_commands.json 效果
> 也不錯」→ 實測。22 題 × 3 臂 × N=3(198 runs,零失敗),同場重跑、
> codex 66 次獨立評分(v6.1 協定修正後,見 §6):**ccodegraph 63/66、
> none(純 grep)60/66、lsp 60/66**。out-of-box 的 clangd LSP 路線
> **與純 grep 同分,成本還高 16%**($0.336 vs $0.290 每分)。原因不是 clangd 不強——是 agent
> **不太用它**:36% 的 runs 一次 LSP 都沒碰(Bash 342 次 vs LSP 117 次,
> 儘管 prompt 明說「請優先用 LSP」),殺手級的 `incomingCalls` 全場只被
> 用 4 次;加上單 config 盲區(`eloop_win.c` 不在 compile DB)靠 grep
> 兜底。**v3 的核心教訓第三次應驗:教學層比工具本身更決定成敗**——
> codegraph(v3)、cbm(v3)、如今業界正統 clangd,全部倒在同一個地方。
> ccodegraph 的 +3 領先與 v4 一致;雙閘控(WRQ-013)、
> includes 計數(WRQ-015)的優勢守住,但 WRQ-014 出現反向案例(LSP 臂
> 兩次跳出字面 `#ifdef` 拿 2 分,ccodegraph 困在字面拿 1)。
> 題庫飽和警訊:三個強臂擠在 60-63/66,鑑別空間只剩 6 分。

本報告獨立完整:三臂 prompt 全文在附錄 A,評分協定在附錄 B,原始資料在
`hard-benchmark/v6-runs/`(198 份執行 JSON + summary)與 `v6-scores/`
(66 份評分 JSON),分析腳本與索引計量在 `v6-analysis/`。

## 目錄

1. [背景與動機](#1-背景與動機)
2. [設計](#2-設計)
3. [LSP 接入的工程記錄](#3-lsp-接入的工程記錄phase-01-發現)
4. [索引成本](#4-索引成本)
5. [結果:分數](#5-結果分數)
6. [N=3 穩定性與評分異常檢查](#6-n3-穩定性與評分異常檢查)
7. [LSP 使用率:工具在場 ≠ 工具被用](#7-lsp-使用率工具在場--工具被用)
8. [題型分解](#8-題型分解)
9. [誠實結論](#9-誠實結論)
10. [限制](#10-限制)
11. [附錄 A:三臂 prompt 全文](#附錄-a三臂-prompt-全文)
12. [附錄 B:評分協定](#附錄-b評分協定)

## 1. 背景與動機

使用者收到外部建議:「用 Claude Code 的 LSP 功能加 compile_commands.json
效果也不錯」(參考:Claude Code plugins 文件的 LSP servers 章 + Reddit
r/ClaudeCode 討論)。這正是 v5 §12.2 戰略警告要的外部訊號——clangd +
compile DB 是**業界正統路線**,如果它以相近成本追平 ccodegraph,產品線
的地基假設(圖工具的邊際價值)受第三次打擊;如果它在雙閘控/巨集/fnptr
題型明顯掉分,則是 ccodegraph「no-build + 多 config 誠實標注」定位的最強
證據。四個設計決定由使用者拍板:①對象 = Claude Code 原生 LSP plugin
機制;②同場重跑 none + ccodegraph 對照(codegraph/cbm 沿用 v3 舊數據);
③LSP 臂只測 out-of-box(README 級說明,與 v3 給 codegraph/cbm 的待遇
一致);④22 題全跑、N=3。

## 2. 設計

| 臂 | 工具 | 條件 |
|---|---|---|
| none | grep/awk/sed/cat/find/Read | v3 prompt 一字不改 |
| ccodegraph | ccodegraph 0.0.6(D17 直讀)+ SKILL + 真實 compile DB + clink | v3 prompt 一字不改 |
| **lsp** | Claude Code 原生 `LSP` 工具(clangd 17 + 真實 compile DB) | 新臂,README 級 prompt(附錄 A) |

共同條件(與 v3/v4/v5 相同):`claude-sonnet-5`、`--max-budget-usd 3`、
`git archive` 乾淨樹、`--setting-sources project`、嚴格循序、timeout
1200s。N=3,執行序 題→rep→臂。harness:`v6-analysis/run_hard_ab_v6.py`。

**LSP 臂的 out-of-box 界定**:prompt 告知工具存在、九個操作名、參數形狀、
載入方式(deferred tool 需 ToolSearch),並說「請優先用 LSP 工具回答,
必要時可搭配少量 grep/cat 覆核」——這與 v3 給 codegraph 的 CLI cheatsheet
同一資訊等級;不教策略、不教陷阱、不給 SKILL 級精調。smoke(2 題 × 3 臂)
確認行為合理後 prompt 凍結,全量未再改動。

## 3. LSP 接入的工程記錄(Phase 0/1 發現)

之後有人要重現這條路線,這些坑各值幾小時:

1. **接入機制**:Claude Code plugin 可宣告 LSP servers(plugin 根目錄
   `.lsp.json`:`command` + `extensionToLanguage`)。官方 marketplace 沒有
   C/C++ plugin——自建 `clangd-lsp` 本地 plugin(10 行 JSON)+ 本地
   marketplace,`claude plugin install clangd-lsp@local-bench --scope
   project` 只寫進專案 `.claude/settings.json` 的 `enabledPlugins`。
   **headless(`claude -p`)+ `--setting-sources project` 下 LSP 完整
   可用**(實測;文件未載明)。agent 拿到名為 `LSP` 的 deferred tool,
   操作:goToDefinition/findReferences/hover/documentSymbol/
   workspaceSymbol/goToImplementation/prepareCallHierarchy/incomingCalls/
   outgoingCalls。
2. **clangd 惰性載入 compile DB**:`initialize` 不會觸發——必須 `didOpen`
   一個 DB 內的檔案,background index 才啟動。漏這步 = 0 個 index shard
   白燒 900s timeout(踩過)。
3. **compile DB 路徑**:`file` 欄可為相對 `directory` 的路徑;wpa 的 112
   entries 全帶絕對 `-I`,搬樹必須重寫 directory/file/output/arguments
   四處前綴。
4. **bear 幽靈條目**:redis 的 DB 357 entries 中 4 條是 configure 探測
   殘留(`foo.c` 不存在)。
5. **快取策略**:clangd index 以絕對路徑為鍵 → lsp 臂用固定工作樹
   (每 run 指紋驗證未被污染),與 v5「預建索引跨 run 重用」政策一致;
   none/ccodegraph 臂維持每 run 新樹(ccodegraph 建圖 3-4s,便宜)。

## 4. 索引成本

| 臂 | 一次性索引 | 每 run 準備 |
|---|---|---|
| none | 0 | 解樹 ~2s |
| ccodegraph | — | 解樹 + build(3-4s)+ clink-import(~30-60s) |
| lsp | clangd 預熱:wpa **22s**(235 shards)/ redis **24s**(379 shards) | 指紋驗證 <1s |

(v3 時代 ccodegraph 建圖要 90-130s/run;D17 之後這項成本幾乎消失,
clink 語意層成為 prep 大頭。)

## 5. 結果:分數

66 份 codex 評分(3-slot,每題每 rep 一次),每格 r1/r2/r3 → 中位數:

| qid | none | ccodegraph | lsp |
|---|---|---|---|
| WRQ-001 | 3/3/3 → 3 | 3/3/3 → 3 | 3/2/3 → 3 |
| WRQ-002 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-003 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-004 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-005 | 3/3/3 → 3 | 3/3/3 → 3 | 3/2/3 → 3 |
| WRQ-006 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-007 | 3/3/3 → 3 | 3/3/3 → 3 | 2/3/3 → 3 |
| WRQ-008 | 3/3/3 → 3 | 3/3/3 → 3 | 3/2/3 → 3 |
| WRQ-009 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-010 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-011 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |
| WRQ-012 | 3/3/3 → 3 | 3/2/3 → 3 | 3/2/3 → 3 |
| **WRQ-013** | 2/3/1 → 2 | 2/3/3 → **3** | 2/2/3 → 2 |
| **WRQ-014** | 1/1/2 → 1 | 1/1/1 → **1** | 2/2/1 → **2** |
| **WRQ-015** | 2/2/2 → 2 | 3/3/3 → **3** | 2/2/2 → 2 |
| WRQ-016 | 3/3/3 → 3 | 3/3/3 → 3 | 3/2/0 → 2 |
| WRQ-017 | 3/2/3 → 3 | 3/2/3 → 3 | 3/2/3 → 3 |
| WRQ-018 | 2/3/3 → 3 | 3/3/3 → 3 | 3/3/2 → 3 |
| **WRQ-019** | 2/3/2 → 2 | 3/2/3 → **3** | 2/2/2 → 2 |
| WRQ-020 | 2/2/2 → 2 | 2/2/2 → 2 | 2/2/2 → 2 |
| WRQ-021 | 3/3/2 → 3 | 3/3/3 → 3 | 3/2/3 → 3 |
| WRQ-022 | 3/3/3 → 3 | 3/3/3 → 3 | 3/3/3 → 3 |

**總分與成本**(3 reps 合計 $59.35):

| 臂 | 總分/66 | 總成本 | 每分成本 | wall 中位 | turns 中位 |
|---|---|---|---|---|---|
| **ccodegraph** | **63** | $21.84 | $0.347 | 49s | 9 |
| none | 60 | $17.38 | **$0.290** | 39s | 6 |
| lsp | 60 | $20.14 | $0.336 | 42s | 10 |

**跨場對照**(不同場次,注意漂移警語):

| 場次 | none | ccodegraph | codegraph | cbm | lsp |
|---|---|---|---|---|---|
| v3(N=1,2026-07-08 前後) | 54 | 58 | 58 | 57 | — |
| v4(N=1,只重跑 ccodegraph) | — | 62 | — | — | — |
| **v6(N=3 中位,同場;v6.1)** | **60** | **63** | — | — | **60** |

ccodegraph 63 與 v4 的 62 跨場相符(教學層改良的效果穩定)。none 從 v3
的 54 升到 60——N=3 中位數平滑 + 模型/環境隨時間變強,**這正是同場重跑
的價值**:v6 的三臂比較才是乾淨的;跨場數字只能看趨勢。

## 6. N=3 穩定性與評分異常檢查

- 66 組 (題,臂) 中 **1 組**跨 rep 變異 ≥2:WRQ-016 lsp = [3,2,0]。
  複核 r3 原始答案:agent 用 grep 數 `#include "server.h"` 數出 66,
  GT 實測 70——真實答案錯誤(且該 run 沒用 LSP),0 分判定正確。
- WRQ-014 的反向(lsp 2 > ccodegraph 1)逐 rep 複核:lsp 臂 r1/r2 跳出
  字面 `#ifdef USE_JEMALLOC`,涵蓋 `#if defined(...)` 寫法與建置層閘控
  → 2;ccodegraph 臂三個 rep 都困在字面拼寫 → 1。真實品質差,非評分
  異常。(諷刺:雙閘控是 v4 教給 ccodegraph 的課,這題的字面陷阱是
  它的變奏——教學層還有下一課可教。)
- 程式化矛盾掃描(score=3 配負面詞/反向):4 個 flag 全為誤報(負面詞
  在正面語境,如「missing list.c」是在稱讚 agent 正確指出該檔不存在)。
- **v6.1 協定修正(2026-07-12,發布後追查發現)**:評分 prompt 原本只餵
  答案前 4,000 字元,而 18/198 個答案超過(WRQ-009 全部 9 個 runs,最長
  5,618)——長清單答案其實**列完了**,評分者卻只看到前段而判「中途斷掉」。
  這是「評分者視圖被工程細節弄殘」教訓的**第四次**現身(前三課見 v5 報告:
  GT 會錯/評分者信錯 GT/GT 視圖被截斷——這次輪到答案視圖)。修正:視窗
  4,000 → 12,000,受影響的 11 個 (題,rep) 格子重評,舊評分留檔
  `*.pre-v61`。影響:WRQ-009 三臂從全 2 平反為全 3(+1 each),另有
  3 個單格 rep 級波動、中位數不變;三臂總分 59/62/59 → **60/63/60**,
  相對結論(+3 margin、lsp=none)完全不變。v5 kernel 亦查出 9 個暴露
  runs 一併重評(見 v5 報告勘誤)。

## 7. LSP 使用率:工具在場 ≠ 工具被用

66 個 lsp 臂 runs 的 transcript 統計:

| 工具 | 呼叫次數 |
|---|---|
| Bash(grep/cat…) | **342** |
| Read | 260 |
| **LSP** | **117** |
| ToolSearch | 57 |

- **24/66 runs(36%)一次 LSP 都沒用**——包括 WRQ-008(呼叫鏈)、
  WRQ-009(fnptr)、WRQ-016(includes 計數)、WRQ-022(debug 情境)
  的全部三個 rep。prompt 明說「請優先用 LSP」仍然如此。
- LSP 操作分布:workspaceSymbol 32、documentSymbol 32、findReferences
  26、goToDefinition 17、hover 5、**incomingCalls 4**、
  prepareCallHierarchy 1、outgoingCalls 0。**呼叫階層——LSP 對決
  callers/callees 的殺手鐧——全場只被碰 5 次。**
- 有用 LSP 的 42 runs 平均 2.62 分 vs 沒用的 24 runs 平均 2.42 分
  (描述性統計,混雜題目難度,不作因果宣稱)。
- smoke 期觀察到的模範行為(WRQ-005 用 goToDefinition 抽驗呼叫解析到
  `object.c:643` 真定義)存在但不穩定——同一題另一個 rep 掉回純 grep。

這是 v3 教訓的第三次重演:**工具的天花板由教學層決定,不由引擎決定**。
codegraph 在 v5 kernel 重演我們 v3 的病徵(14 次 `--help`、192KB 輸出);
clangd 這次不是浪費 token,而是**乾脆不被想起**——agent 的預設肌肉記憶
是 grep,「優先用 X」一句話撼不動它。ccodegraph 的 62 分有多少來自
SKILL 教學層,v4 的 before/after(58→62)已經量過:大部分。

## 8. 題型分解

**理論預測命中的**:

- **WRQ-013(雙閘控,`#ifdef CONFIG_*` × Makefile)**:ccodegraph 3
  (SKILL 的雙閘控教學,v4 遺產),none/lsp 各 2。clangd 的單 config
  視角在這題結構性受限:另一個 config 的分支它根本沒編譯。
- **WRQ-015(who-includes 精確計數)**:ccodegraph 3(includes 邊直查),
  none/lsp 2。LSP 沒有「誰 include 這個 header」查詢(protocol 沒這個
  method),agent 只能 grep,回到 v1 時代 `"eloop.h"` vs `"utils/eloop.h"`
  兩種寫法的老陷阱。
- **單 config 盲區**:smoke 期即現形——`eloop_win.c` 不在 compile DB,
  findReferences 對它全盲;agent 用 grep 補上並誠實揭露。全量中這類
  補償行為反覆出現:**LSP 臂的正確性有相當比例其實是 grep 在撐**。

**理論預測落空的**:

- **WRQ-009(fnptr 分派)**:預測 LSP 弱,v6.1 修正後實際三臂同
  3/3/3——原始評分的全 2 是視窗截斷假象(§6)。三臂都用 grep 列完了
  96 項;lsp 臂三個 rep 完全沒用 LSP(incomingCalls 沒上場),工具
  弱點未被測到,是「工具未被使用」蓋過了。
- **WRQ-014(`#ifdef USE_JEMALLOC` 枚舉+分類)**:LSP 臂反而最高(2)
  ——但細看 transcript,優勢來自 agent 那兩次「跳出字面拼寫」的搜索
  策略,與 LSP 工具無關。歸因要誠實:這是 agent 行為方差,不是 clangd
  的功勞。

## 9. 誠實結論

1. **out-of-box 的 clangd LSP 路線在本題庫上 = 純 grep(59 vs 59),
   成本高 16%**。外部建議「效果也不錯」在 out-of-box 條件下不成立——
   它不比 grep 差,但也沒賺到 clangd 的語意精度,因為 agent 大部分時間
   沒在用它。
2. **ccodegraph 守住 +3**,且雙閘控/includes 兩類優勢題正是「no-build
   多 config 誠實標注」定位的證據題。但 margin 從 v3 的 +4 縮到 +3,
   且 62 分裡教學層貢獻居多(v4 已量:+4 全來自教學改良)。
3. **對 clangd 路線的公平陳述**:它的天花板遠沒被測到。一份 SKILL 級的
   LSP 教學層(什麼題型用 incomingCalls、何時信 findReferences、單 config
   盲區怎麼補)很可能把 59 拉高好幾分——那是使用者明確排除的「精調臂」
   (out-of-box 才是本輪問題)。這個未測的天花板本身就是發現:**工具
   作者不寫教學層,工具就只值 grep 的分數**。
4. **題庫飽和警訊**:三個強臂擠在 60-63/66,6 分鑑別空間;22 題中 16 題
   三臂中位數全 3 或全同分。這題庫是 v2 時代為「grep vs 圖」設計的,
   對 2026 年中的 Sonnet 5 已太簡單。若還要第七輪,先換題(更深的跨檔
   推理、更大的 repo、或 kernel 20 題移植過來),否則量到的只是噪音。
5. **回到戰略層**(v5 §12.2 凍結令):這輪回答了外部建議,結論支持
   「教學層與 benchmark 方法論是最可轉移資產」的判斷——連業界正統
   clangd 都需要教學層才能發揮。投放收反饋仍是下一步;本報告本身就是
   好素材(「我們把 clangd+compile DB 當對照組測了」是社群會感興趣的
   標題)。

## 10. 限制

- LSP 臂只測 out-of-box;精調教學層的天花板未測(使用者明確的範圍決定)。
- 單一模型(claude-sonnet-5)、單一日期窗;none 54→59 的跨場漂移說明
  絕對分數不可跨場直比。
- codegraph/cbm 未同場重跑(成本考量,使用者拍板);它們的 v3 數字只能
  看趨勢。
- compile DB 覆蓋:wpa 112 TU(CONFIG_DRIVER_WIRED+SAE+AP 組態,
  driver_nl80211.c 缺席——macOS 無 Linux 核心 header)、redis 353 真實
  TU;LSP 對 DB 外檔案全盲是**真實使用條件**而非不公平——這正是
  compile-DB 路線的固有屬性。
- 評分:codex 單一評分者,3-slot 同場(v3/v4 為 4-slot;anchoring 差異
  理論上存在,rubric 文字一字未改以最小化)。

## 增補:敗因診斷與「使用時機提示」實驗(2026-07-12)

v6 收尾後追問:LSP 臂為什麼沒贏 grep——是題目結構,還是該教 agent
「什麼時候用 LSP」?四層診斷 + 一個 9-run 探針實驗(原始資料
`v6-analysis/hint-probe/`):

**① rep 級輸贏解剖(66 組)**:lsp 贏 5 / 平 49 / 輸 12。12 個輸的
rep 中:4 個**全程沒用 LSP**、輸在 grep 草率(WRQ-016 數錯 66≠70、
WRQ-019 誤含 `bio_threads[]`);8 個有用 LSP 但輸在**推理/表述層**
(WRQ-005 列全 7 行卻總結說 6、WRQ-007 清單全對但解釋多說錯話)——
沒有任何一個輸是 LSP 回錯資料造成的。

**② 結構性摩擦**:LSP API 是 position-based(要先知道 file:line:char
才能問)→ grep 天生是前置步驟。42 個有用 LSP 的 runs 裡 25 個先
Bash 後 LSP(工具當覆核器不當主力);117 次 LSP 呼叫 26% 回空/錯
(單 config 索引外的符號、定位不準)。

**③ 題目結構**:22 題按「LSP 原語能否直接回答」分類——直接可答
(def/refs/callers)9 題,全落在三臂同 3 的飽和區;**鑑別題(13/14/
15/16/19/20)全落在 LSP 無原語區**(#ifdef 枚舉、who-includes 計數、
併發推理)。題庫的鑑別軸恰好垂直於 LSP 的能力軸。

**④ 提示實驗**(prompt 加一句使用時機教學:「callers 類問題先定位再
findReferences/incomingCalls;枚舉計數題用 LSP 與 grep 互相覆核」,
三題 × 3 reps):

| 題 | 基線中位 | 提示版 | LSP 使用(提示版 9 runs) |
|---|---|---|---|
| WRQ-019(應有效區) | 2 | **3** | r2 用 2 次,r1/r3 = 0 |
| WRQ-016(負對照,無原語) | 2 | **3** | 0/0/0 |
| WRQ-009(fnptr) | ~~2~~ 3(v6.1) | ~~2~~ 3(v6.1,中位) | 只 r2 用 3 次 workspaceSymbol |

**機制歸因(最重要的發現)**:兩題的升分 run 一次 LSP 都沒用——
起效的是提示裡「**兩種方法互相覆核計數**」那半句(覆核紀律),與
LSP 完全無關;WRQ-016 負對照升分證死了這點。而「使用時機」半句對
使用率幾乎無效:9 個提示 run 只有 2 個碰 LSP——一句話推不動 grep
肌肉記憶。

**v6.1 勘誤(2026-07-12)**:本增補初版曾稱「WRQ-009 不動,敗因是
枚舉耐力(列到 77/96 斷掉)」——**撤回**。那是評分視窗截斷假象
(§6 v6.1):基線與提示版的答案其實都列完了,修正視窗後基線
3/3/3、提示版 3/2/3。WRQ-009 從「耐力案例」變成「假象案例」;
本增補的主結論(紀律 > 使用時機提示)不受影響,因為它建立在
WRQ-019/016 上,兩題答案皆短、不受視窗影響。

**結論**:「題目還是提示?」——都是,但權重排序:①題目結構(鑑別
區沒有 LSP 原語)>②覆核紀律(可教、通用、與工具無關——ccodegraph
62 分的 SKILL 教的正是這個)>③使用時機提示(單句無效;要動搖工具
選擇習慣需要 SKILL 級教學層 + 會獎勵語意精度的題型,如重命名衝突、
同名多義、跨 TU 型別問題)。

## 附錄 A:三臂 prompt 全文

**none**:
> 你在一個 C 專案 repo(唯讀複本)。只能用 shell 指令(grep/awk/sed/cat/find/Read)探索原始碼,不要安裝或呼叫任何額外工具,也不要嘗試連網。任務:{question} 回答精簡但完整,不要省略你找到的細節列表。不要修改任何檔案。

**ccodegraph**:
> 你在一個 C 專案 repo(唯讀複本)。這裡有 ./ccodegraph.py 這個程式碼知識圖工具,圖已經建好在 .ccodegraph/(這次用真實 compile_commands.json 建圖,非合成)。請用它來回答,必要時可以搭配它的 sql 逃生口或少量 grep 覆核可疑答案。任務:{question} 回答精簡但完整,不要省略你找到的細節列表。不要修改任何檔案。

**lsp**(本輪新增,smoke 後凍結):
> 你在一個 C 專案 repo(唯讀複本)。這個環境已啟用 clangd LSP(讀取專案根的真實 compile_commands.json,單一建置組態,索引已預熱)。有一個 `LSP` 工具(若不在目前工具清單,先用 ToolSearch query="select:LSP" 載入),操作:goToDefinition / findReferences / hover / documentSymbol / workspaceSymbol / goToImplementation / prepareCallHierarchy / incomingCalls / outgoingCalls;參數 filePath + line + character(1-based;workspaceSymbol 另用 query 參數)。請優先用 LSP 工具回答,必要時可搭配少量 grep/cat 覆核可疑答案。任務:{question} 回答精簡但完整,不要省略你找到的細節列表。不要修改任何檔案。

## 附錄 B:評分協定

codex(`codex exec --sandbox read-only --output-schema`)3-slot 評分,
每 (題, rep) 一次共 66 次;GT = `questions.jsonl` 的 evaluation_notes +
`gt_WRQ-XXX.md` 全文(前 7000 字);rubric 與 v3/v4/v5 一字不改
(0=錯/捏造、1=大錯或嚴重不完整、2=大致正確但有 GT 點名的缺口、
3=完全正確;獨立判定、引用 GT 依據)。完整 prompt 模板:
`v6-analysis/score_v6.py`。異常檢查三件套(§6)照 v3 慣例。
