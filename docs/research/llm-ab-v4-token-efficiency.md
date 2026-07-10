# R4 驗收 v4:ccodegraph token 效率改善(D16)——before/after 全量重跑與獨立完整報告

> **後續**:v5 把戰場搬到 Linux kernel v6.6(索引可行性三工具全滅、8,170 檔
> 子樹四臂對決、N=3、速度實測),見 [`llm-ab-v5-linux-kernel.md`](llm-ab-v5-linux-kernel.md)。

> **TL;DR**:針對 v3 發現的「ccodegraph 是 4 個工具臂中每分正確性成本最高」問題,
> 做了三項工具層改善(輸出顯式截斷 D16、SKILL 全面重寫、`--help` 內嵌教學),
> 用與 v3 完全相同的條件(Sonnet 5、同 22 題、同隔離、同 harness prompt、codex
> 獨立評分)全量重跑 ccodegraph 臂一次。結果:**分數 58/66 → 62/66(+4,四臂
> 最高分),總成本 $7.99 → $7.74(-3%),每分正確性成本 $0.138 → $0.125(-9.4%)**;
> 啟動儀式浪費(`--help`×7、`schema`×12、`status`×6)全部歸零,tool_result
> 總位元組 -32%。一題真實退步(WRQ-005,agent 又犯了「列表對、加總錯」的通病),
> 五題真實進步(012/013/014/016/019),全部逐題人工複核過評分依據。

本報告設計為**獨立完整**:不需翻其他檔案即可看到每題的題目原文、GT 要點、
評分標準、before/after 結果與 codex 判定理由(附錄 A),以及 codex 判定用的
prompt 模板原文(附錄 B)。原始數據(22 份 v4 執行 JSON、22 份 codex 評分
JSON、transcript 分析)在 `hard-benchmark/v4-runs/`、`hard-benchmark/v4-analysis/`。

## 目錄

1. [動機:v3 的負面發現](#1-動機v3-的負面發現)
2. [改了什麼、為什麼、沒改什麼](#2-改了什麼為什麼沒改什麼)
3. [迭代記錄(含失敗)](#3-迭代記錄含失敗)
4. [Before/After 總表與四工具對照](#4-beforeafter-總表與四工具對照)
5. [Token 熱點 before/after](#5-token-熱點-beforeafter)
6. [codex 評分異常檢查](#6-codex-評分異常檢查)
7. [誠實結論](#7-誠實結論)
8. [未來改善方向](#8-未來改善方向)
9. [附錄 A:22 題逐題完整資料](#附錄-a22-題逐題完整資料)
10. [附錄 B:codex 判定 prompt 模板原文](#附錄-bcodex-判定-prompt-模板原文)

## 1. 動機:v3 的負面發現

v3(`llm-ab-v3-full-suite.md`,22 題 × 4 工具 × Sonnet 5)的 token 熱點分析:

| Arm | 總花費 | 總分/66 | 每分成本 |
|---|---|---|---|
| none(純 grep) | $5.77 | 54 | $0.107 |
| codegraph | $6.86 | 58 | $0.118 |
| cbm | $7.37 | 57 | $0.129 |
| **ccodegraph(v3)** | **$7.99** | **58** | **$0.138** ← 最貴 |

且**最貴的題目是最簡單的題目**(vs 其他臂最低價:WRQ-001 貴 2.58×、WRQ-005
2.34×、WRQ-015 2.11×;最難的 WRQ-008 反而 0.95× 佔優)。逐指令解剖三個最貴
案例,浪費集中在三類:

1. **啟動儀式**:`--help`(7 次,15.2KB——SKILL 舊版說「不用查 --help」但沒附
   語法,agent 只好查)+ `schema`(12 次——舊版 SKILL 第 34 行明教「always
   start with schema」)+ `status`(6 次)。
2. **無界輸出爆量**:`callers decrRefCount` 一次 27.9KB(數百 repo 級 caller,
   題目只問一個檔案);`ls` repo 根目錄一次 27.3KB;無 LIMIT 的 sql 6.8KB。
3. **遊蕩**:`cd` 32 次 54.4KB(其他臂 4–18 次)。

另一個結構性事實(改善過程中才確認):**專案 skill 不是自動進 context 的**——
它以 name+description 形式被宣告,agent 要主動 Invoke 才載入內容。v3 的浪費
行為部分來自「agent 根本沒讀過 SKILL 就開始用工具」。

## 2. 改了什麼、為什麼、沒改什麼

三項改善全部是「工具出貨物」層面(ccodegraph.py + SKILL.md),對應到 D16
決策記錄(`docs/design.md` §8.5.5):

**(a) D16 輸出顯式截斷**(`ccodegraph.py`):`callers`/`callees`/`explore`
每節預設截斷於 40 筆、`sql` 預設 200 行,新 flag `--limit N` 覆蓋(0=不限)。
**截斷永遠顯式、真實總數永遠可見**(尾行 `… +N more (total T; use --limit 0
for all)`、explore 節標題印真實總數、JSON 帶 `total`/`truncated` 欄位)——
隱性截斷會毀掉枚舉題正確性,顯式截斷+總數可見則保留 agent 的決策權。
單元測試 10 個(`tests/unit/test_limits.py`),含「剛好等於上限不誤報」邊界。

**(b) SKILL.md 全面重寫**(13,117B → 6,597B):完整指令 cheatsheet(每個 verb
精確語法)、刪除「Step 0 必跑 schema」改為「圖已就緒直接查」、內嵌 DDL、
新增 token 紀律章(scoped SQL、窄讀 Read offset/limit、COUNT 交叉核對總數、
不 ls 根目錄、不 cd)、信任校準與盲點章壓縮保留(這些在 v2/v3 拿分)。
frontmatter description 開頭改為「Invoke FIRST…」提高載入率。

**(c) `--help` 內嵌教學**(argparse epilog):agent 沒載 skill 時,第一次
`--help` 就拿到精簡 cheatsheet + token 紀律,把浪費呼叫變成教學時刻。

**沒改什麼(歸因乾淨)**:harness 的 arm prompt 模板一字不改;22 題題目、GT、
隔離手法(git archive 乾淨複本 + `--setting-sources project`)、
`--model claude-sonnet-5`、真實 compile_commands.json、預建圖流程全部與 v3
相同;不動 schema/引擎/建圖邏輯。

## 3. 迭代記錄(含失敗)

使用者明示「可嘗試不同的方法,失敗也沒關係,錯誤也是一種成功,但不要越做越
糟糕」——smoke set(5 題:三個最貴的 001/005/015 + 兩個難題 008/013)閘門
迭代如下,全部誠實記錄:

**Smoke 1(截斷+新 SKILL)**:分數 14→15(WRQ-013 從 2 升到 3!),但成本
+6%——透過 transcript 發現**5 題中只有 1 題的 agent 真的 Invoke 了 skill**,
其餘 4 題沒看過 cheatsheet、照跑舊儀式;有載入 skill 的那題(WRQ-001)
2 個呼叫就答完(-45%)。→ 催生迭代 1。

**迭代 1(--help epilog + description 強化)後 re-smoke WRQ-008/013**:
WRQ-008 $0.434(v3)→$0.369(-15%)✓;但 **WRQ-013 出現真實退步:$0.525
(-21%)卻只拿 1 分**(v3=2)——便宜的那次跑淺了,完全漏掉 Makefile 整檔
閘控的 sae.c(35 個函式)。這是這輪最有價值的失敗:**省 token 和挖得深在
這類 build-system 題上直接對撞**。

**迭代 2(雙閘控機制教學)**:把「條件編譯有兩種機制:in-file `#ifdef` AND
Makefile 檔案級閘控」寫進 SKILL 盲點章與 epilog。這是可泛化的 C 領域知識
(v3 報告的改善清單第 3 條早已點名、GT 建構自己也在這裡連錯兩次),不是
題目特定答案;但它確實是**看到 WRQ-013 退步後才加的**,此點如實記錄。
re-smoke WRQ-013:$1.282、36 turns、**3 分(滿分)**——貴,但錢花在會換分
的深度驗證上。

**全量重跑閘門判定**:smoke 最終分數 15/15 possible(v3 同組 14)、三個最貴
題 -45%/-44%/-4% → 進入全量。

## 4. Before/After 總表與四工具對照

22 題逐題(分數 = codex 同協議判定;成本 = headless `total_cost_usd`):

| 題號 | v3 分 | v4 分 | v3 成本 | v4 成本 | Δ成本 |
|---|---|---|---|---|---|
| WRQ-001 | 3 | 3 | $0.336 | $0.149 | **-56%** |
| WRQ-002 | 3 | 3 | $0.216 | $0.187 | -14% |
| WRQ-003 | 3 | 3 | $0.265 | $0.363 | +37% |
| WRQ-004 | 3 | 3 | $0.187 | $0.279 | +49% |
| WRQ-005 | 3 | **2** ↓ | $0.338 | $0.159 | **-53%** |
| WRQ-006 | 3 | 3 | $0.199 | $0.179 | -10% |
| WRQ-007 | 3 | 3 | $0.241 | $0.172 | -29% |
| WRQ-008 | 3 | 3 | $0.434 | $0.413 | -5% |
| WRQ-009 | 2 | 2 | $0.298 | $0.302 | +1% |
| WRQ-010 | 3 | 3 | $0.481 | $0.453 | -6% |
| WRQ-011 | 3 | 3 | $0.216 | $0.173 | -20% |
| WRQ-012 | 2 | **3** ↑ | $0.281 | $0.249 | -12% |
| WRQ-013 | 2 | **3** ↑ | $0.664 | $1.207 | **+82%** |
| WRQ-014 | 1 | **2** ↑ | $0.330 | $0.253 | -23% |
| WRQ-015 | 3 | 3 | $0.470 | $0.301 | -36% |
| WRQ-016 | 2 | **3** ↑ | $0.200 | $0.161 | -19% |
| WRQ-017 | 3 | 3 | $0.443 | $0.386 | -13% |
| WRQ-018 | 3 | 3 | $0.941 | $1.032 | +10% |
| WRQ-019 | 2 | **3** ↑ | $0.460 | $0.455 | -1% |
| WRQ-020 | 2 | 2 | $0.265 | $0.173 | -35% |
| WRQ-021 | 3 | 3 | $0.401 | $0.407 | +1% |
| WRQ-022 | 3 | 3 | $0.327 | $0.290 | -12% |
| **合計** | **58** | **62** | **$7.99** | **$7.74** | **-3%** |

16/22 題變便宜;漲價集中在深度驗證換分的 WRQ-013(+82%,2→3 分)與本來就深
的 WRQ-018(+10%)。成本輪廓正是設計目標:**簡單題大幅便宜(-56%/-53%),
難題把錢花在換分的深度上**。

四工具最終對照(none/codegraph/cbm 為 v3 值,ccodegraph 為 v4 值——三個
對照臂未重跑,此點需注意;grader 噪音見 §6):

| Arm | 總分/66 | 總成本 | 每分成本 |
|---|---|---|---|
| none(v3) | 54 | $5.77 | $0.107 |
| codegraph(v3) | 58 | $6.86 | $0.118 |
| cbm(v3) | 57 | $7.37 | $0.129 |
| **ccodegraph(v4)** | **62** | $7.74 | **$0.125** |

ccodegraph 從「最貴、分數並列」變成**四臂最高分**,每分成本擠進 codegraph
與 cbm 之間;總成本仍是第二高——省下的錢一部分被再投資到深度驗證。

## 5. Token 熱點 before/after

對 22 份 v4 transcript 重跑與 v3 相同的逐 tool_result 位元組分析:

| 指令簽名 | v3 呼叫/bytes | v4 呼叫/bytes | 判讀 |
|---|---|---|---|
| `ccodegraph --help` | 7 / 15,246 | **0 / 0** | cheatsheet 內嵌生效 |
| `ccodegraph schema` | 12 / 6,290 | **0 / 0** | 「圖已就緒」+內嵌 DDL 生效 |
| `ccodegraph status` | 6 / 7,288 | **0 / 0** | 同上 |
| `ls` | 7 / 55,542 | 6 / 6,907 | 不再 ls 整個根目錄 |
| `cd`(含複合指令) | 32 / 54,405 | 4 / 2,675 | 「留在根目錄用 -p .」生效 |
| `ccodegraph callers` | 1 / **27,862** | 2 / **1,711** | D16 截斷在真實環境生效 |
| `ccodegraph explore` | 16 / 70,495 | 25 / 56,229 | 次數增、單價降(截斷) |
| `ccodegraph sql` | 24 / 26,278 | 35 / 22,337 | 更常用、更小(LIMIT 紀律) |
| Read | 31 / 158,366 | 57 / 173,590 | 次數近倍增、單次 5.1KB→3.0KB(窄讀) |
| grep | 29 / 19,401 | 51 / 30,971 | 覆核用量增加(換分數的驗證) |
| **總計** | 206 / 488,306 | 222 / **333,988** | **-32% tool_result bytes** |

另外兩個過程指標:**Skill 載入 22/22**(「Invoke FIRST」description 生效;
smoke1 時只有 1/5);turns 237→266(+12%——更多但更便宜的回合,多出來的
主要是難題上的窄讀與覆核,正是換到 +4 分的那部分工作)。

## 6. codex 評分異常檢查

使用者要求「再檢查 codex 產出的結果有沒有異常」。三層檢查:

**(1) 程式化掃描**(v3 的 22 份 + v4 的 22 份全部):找「理由高度讚美但分數
≤1」「理由強烈批評但給 3 分」「理由引用 GT 沒有的事實」等矛盾模式。結果:
v3 零可疑;v4 一筆命中是啟發式誤報(WRQ-011 codegraph 的理由「Fully matches
the GT by stating list.c is absent…」被關鍵詞觸發,實為讚美句)。

**(2) 錨定臂變異量測**(這輪方法論的意外收穫):v4 評分沿用與 v3 完全相同的
4-slot prompt,只把 ccodegraph 槽換成新答案——**另外三個槽是與 v3 一字不差
的相同答案**,等於天然的評分者重測實驗。結果:66 個錨定分數中有 **6 個漂移**
(±9%/題),其中 WRQ-012 三個錨定臂全部 2→3(該題第二輪整體偏鬆)、WRQ-013
的 cbm 3→2、WRQ-007/016 的 none 各 +1。**含義:單題 ±1 分是 grader 噪音
正常範圍,v4 的 +4 總分超出噪音帶,但逐題升降需個別驗證**(見下)。

**(3) 逐題人工複核**(所有分數變動題,回到原始答案與 GT):
- **WRQ-005(3→2,唯一退步)**:真實扣分。v4 答案的表格列出全部 7 個正確
  行號(128/207/543/894/1347/1629/1630,與 GT 完全一致),但總結兩度寫
  「共 6 處」,還把「14 個邊 ÷ 2 引擎」算成 6——**「列表對、加總錯」這個
  v2/v3 已三次觀察到的模型通病再次出現**;新 SKILL 的 COUNT 紀律降低了但
  沒根絕它(這次 agent 有跑 COUNT,但把去重前後的數字搞混)。codex 依 GT
  規則(總數必須正確)扣分合理。
- **WRQ-012(2→3)**:真實進步,非僅 grader 漂移——v3 答案把 `type`/
  `encoding`/`metabits` 誤列為 refcount 相關(v3 被扣的正是這點),v4 明確
  寫「其餘欄位不參與引用計數判斷,僅在釋放路徑用到」。但注意此題錨定臂也
  整體偏鬆,+1 中可能有 grader 成分。
- **WRQ-013(2→3)**:真實進步,smoke3 已逐項核對(49 whole + 9 partial =
  58,含 Makefile 閘控的 sae.c 35 個,與 GT 完全一致)。
- **WRQ-014(1→2)**:真實進步——v3 只找到 4 個 USE_JEMALLOC 位置,v4 找齊
  GT 要求的 13 個檔案;仍漏 Makefile 層效果與 HAVE_BACKTRACE 精確計數,2 分
  合理。
- **WRQ-016(2→3)**:真實進步——v4 用 SQL COUNT/DISTINCT 交叉核對(新
  SKILL 教的紀律),v3 的「76−5」內部矛盾算術消失。
- **WRQ-019(2→3)**:真實進步——v3 被扣的「過度列入 GT 明確排除的
  bio_worker_title[]」在 v4 消失,錨定臂此題無漂移。

**結論:+4 分中至少 +3(013/014/019)有堅實的內容根據且錨定穩定;012/016
的 +2 有真實內容改善但疊加了部分 grader 寬鬆;-1(005)是真實的 agent 算術
錯。保守陳述:v4 ≥ v3 高置信,精確增幅在 +2~+4 之間。**

## 7. 誠實結論

1. **效率目標達成方式與預期不同**:總成本只降 3%(未達「< $6.86 超越
   codegraph」的目標),但**每分成本 -9.4%、分數 +4**——省下的儀式浪費被
   模型再投資到深度驗證,而深度驗證在這套題庫上會換分。「token 效率」的
   正確度量是每分成本,不是總成本。
2. **三項改善各自的因果證據都在 transcript 裡**:`--help`/`schema`/`status`
   歸零(cheatsheet 內嵌 + 圖已就緒宣告)、callers 爆量 27.9KB→1.7KB(D16
   截斷)、cd/ls 遊蕩 -91%(紀律章)、Skill 載入 1/5→22/22(description
   改寫)。
3. **省 token 與挖得深會對撞,需要顯式權衡**:WRQ-013 的三次 smoke(3 分
   $1.04 → 1 分 $0.52 → 3 分 $1.28)是最清楚的展示。這輪的選擇是「簡單題
   省下的錢,允許難題花掉」——淨效果是 -3% 成本 +4 分。
4. **「列表對、加總錯」是跨工具、跨模型、跨輪次的頑固通病**(v2 Arm A、
   v3 CodeGraph×2、v4 WRQ-005),教學紀律能降低頻率但不能根絕;真正的解法
   可能要在工具端(例如 verb 輸出自帶 machine-checkable 計數行)。
5. **評分者噪音是真實存在的 ±1/題**,靠錨定臂重測量化出來(6/66)。任何
   單題 ±1 的結論都應標注這個誤差棒;本輪 +4 的總增幅超出噪音帶。

## 8. 未來改善方向

- **對照臂同輪重跑**:本輪只重跑了 ccodegraph 臂,none/codegraph/cbm 沿用
  v3 數據——嚴格的同輪四臂對照(消除跨日/模型版本漂移)留待下次。
- **N=3 重複**:v3/v4 均為 N=1;WRQ-013 的高變異(1↔3 分)說明這類題需要
  重複取樣才能給出穩定結論。
- **A/B 消融**:三項改善(截斷/SKILL/epilog)是打包出貨的,個別貢獻未拆分;
  消融實驗(只上截斷、只上 SKILL)可以量化各自份額。
- **總數自動核對**:在 verb 輸出尾行加 machine-generated 計數(如
  `TOTAL=7 unique sites`),從根源壓制「列表對、加總錯」。
- **schema 層建模缺口不變**(v3 結論仍成立):struct-literal 欄位枚舉、
  條件編譯函式歸戶在所有圖工具上仍退化為 grep;kconfig-build 層與 Makefile
  OBJS 解析是下一個結構性提升點。
- **grader 多數決**:單一 codex 判定 + 錨定重測已量化出 ±9% 噪音;正式版
  可用 3 個獨立評分取中位數。

---

## 附錄 A:22 題逐題完整資料

每題含:題目原文(verbatim)、GT 要點與評分標準(含來源檔案)、before/after
分數與成本、v4 codex 判定理由。

### WRQ-001 [wpa] [symbol-definition/L1]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find the definition of eloop_register_timeout(). Return file, line, and full signature.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-001.md`):VERIFIED 2026-07-07. Definition: src/utils/eloop.c:601, `int eloop_register_timeout(unsigned int secs, unsigned int usecs, eloop_timeout_handler handler, void *eloop_data, void *user_data)`. eloop.h:179 confirmed a declaration only. Build-system note: a second, platform-alternate definition exists at src/utils/eloop_win.c:237 (selected only for native Windows builds via CONFIG_ELOOP=eloop_win) — not a competing answer since this question has no scope limiter, but citing eloop_win.c ALONE (missing the default eloop.c) should be scored down. Full detail: gt_WRQ-001.md.

**結果**:v3(before)= 3 分/$0.336/8t → v4(after)= 3 分/$0.149/5t

**v4 codex 判定理由**:Provides the required file, line, and full signature for the canonical definition in `src/utils/eloop.c:601`. The claim that it is the only definition node misses the Windows alternate, but the GT says mentioning that alternate is optional, so the core answer is fully correct.

### WRQ-002 [redis] [symbol-definition/L1]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find the definition of createStringObject(). Return file, line, and full signature.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-002.md`):VERIFIED 2026-07-07. Definition: src/object.c:338, `robj *createStringObject(const char *ptr, size_t len)`. Declared at src/object.h:139 (not directly in server.h — server.h only pulls it in transitively via #include "object.h"). No Makefile gating (object.o compiled unconditionally). Confusable sibling names to watch for: tryCreateStringObject, createStringObjectFromLongLong(WithOptions/ForValue/WithSds), createStringObjectFromLongDouble. Full detail: gt_WRQ-002.md. CORRECTION 2026-07-08: this GT originally missed a real second, unrelated definition at deps/hiredis/hiredis.c:125 (a static, di…

**結果**:v3(before)= 3 分/$0.216/6t → v4(after)= 3 分/$0.187/7t

**v4 codex 判定理由**:Answer B fully matches the corrected GT by reporting both real same-name definitions, including src/object.c:338 with the correct signature and deps/hiredis/hiredis.c:125 as a static unrelated helper. Extra caller/count metadata is not needed, but it does not contradict the required answer.

### WRQ-003 [wpa] [symbol-definition/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find the definition of struct wpa_driver_ops. Return file, line, and total number of function-pointer fields.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-003.md`):VERIFIED 2026-07-07 — DRAFT NUMBER WAS WRONG. struct wpa_driver_ops defined at src/drivers/driver.h:1633. Actual function-pointer field count is **142**, not 136 (confirmed independently by 3 methods in the GT-construction pass AND spot-checked again directly: `awk` range-extract + regex count on `(*name)(` = 142). The '136' figure had been repeated uncritically in gt_case1_driver_ops.txt's header comment and in WRQ-009's own question text — it was never independently verified before this pass. 22 of the 142 are #ifdef-gated (1 ANDROID driver_cmd + 21 CONFIG_MACSEC fields); this repo's own .co…

**結果**:v3(before)= 3 分/$0.265/10t → v4(after)= 3 分/$0.363/12t

**v4 codex 判定理由**:Correctly reports `src/drivers/driver.h:1633`, closing line 3442, and 142 function-pointer fields. The verification narrative aligns with the GT's regex/range-count method and does not confuse declarations or initializers with the struct definition.

### WRQ-004 [wpa] [references-usages/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:List every real code reference to eloop_remove_timeout() under src/, excluding any occurrence inside a string literal (e.g. debug log messages) or comment.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-004.md`):VERIFIED 2026-07-07. Total real references: 10, split across two platform-alternate eloop backends: src/utils/eloop.c (def 652; calls 674,702,1008,1084) and src/utils/eloop_win.c (def 285; calls 305,333,594,656) — each unconditionally compiled for its own target, no Makefile trap applies to either. Zero false positives (no wpa_printf/wpa_msg string or comment mentions the symbol) — this particular symbol has a clean answer set; the real difficulty is recall across two backend files, not precision filtering. Full detail: gt_WRQ-004.md.

**結果**:v3(before)= 3 分/$0.187/5t → v4(after)= 3 分/$0.279/9t

**v4 codex 判定理由**:Matches the complete GT set of 10 references with correct file:line entries and no false positives. The compile_commands note does not incorrectly exclude eloop_win.c; it still counts the Windows backend because the question is scoped to src/.

### WRQ-005 [redis] [references-usages/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:List every real code reference to decrRefCount() within src/t_string.c only, excluding comments.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-005.md`):VERIFIED 2026-07-07. Real reference count: exactly 7 (src/t_string.c lines 128,207,543,894,1347,1629,1630), all genuine decrRefCount(...) calls. Excluded comment at line 186 confirmed exact (not drifted). Cross-checked via grep -c and independent awk pass (both agree: 8 total hits = 7 real + 1 comment). No #ifdef gating in this file. Full detail: gt_WRQ-005.md.

**結果**:v3(before)= 3 分/$0.338/10t → v4(after)= 2 分/$0.159/6t

**v4 codex 判定理由**:It lists all 7 correct call lines and excludes the line 186 comment, but it repeatedly states the total is 6, which directly conflicts with the GT's required count of 7.

### WRQ-006 [wpa] [caller-callee/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:Function freq_cmp() in src/utils/common.c is never called directly. Find every place it is passed BY NAME as an argument (not called), and name the calling function and call site.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-006.md`):VERIFIED 2026-07-07. Exactly one by-name-passing site: int_array_sort_unique() at src/utils/common.c:895, `qsort(a, alen, sizeof(int), freq_cmp)`. Confirmed exhaustive via 3 independent grep methods (all return only the definition line 873 + this one site) and structurally guaranteed by freq_cmp's `static` linkage (no header prototype, so no other translation unit could reference it). No Makefile/​#ifdef gating on common.c. Scope trap noted: int_array_sort_unique()'s own callers (wpa_supplicant/scan.c, utils_module_tests.c) do NOT name freq_cmp and should not be credited. Full detail: gt_WRQ-0…

**結果**:v3(before)= 3 分/$0.199/8t → v4(after)= 3 分/$0.179/8t

**v4 codex 判定理由**:Correctly gives the sole site, function, file/line, and callee `qsort()`, and notes `freq_cmp` is `static` and not directly called. No transitive callers or extra sites are incorrectly included.

### WRQ-007 [redis] [caller-callee/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find every function in src/t_string.c that calls setKeyByLink() (defined in src/db.c), directly or by first calling setGenericCommand().

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-007.md`):VERIFIED 2026-07-07. Exactly 5 functions in src/t_string.c reach setKeyByLink(): setGenericCommand (depth 1, t_string.c:87→181), setCommand/setnxCommand/setexCommand/psetexCommand (depth 2, each calling setGenericCommand). getexCommand/increxCommand do NOT reach it (they only call setExpire, a sibling). The mset* family DOES reach setKeyByLink but only via a third, unlisted path (setKey() wrapper in db.c:742) — correctly excluded per the question's literal wording ("directly or by first calling setGenericCommand()"). No #ifdef/Makefile gating on either file. Full detail: gt_WRQ-007.md.

**結果**:v3(before)= 3 分/$0.241/8t → v4(after)= 3 分/$0.172/6t

**v4 codex 判定理由**:It reports exactly the five expected functions: setGenericCommand directly, plus setCommand, setnxCommand, setexCommand, and psetexCommand via setGenericCommand. It also excludes other setKeyByLink callers outside t_string.c, which is consistent with the requested scope.

### WRQ-008 [redis] [entry-path/L4]

**題目原文(verbatim,兩輪 harness 一字不差)**:Trace the full call path from Redis command dispatch to the lowest-level database write for the SET command: from lookupCommand()/processCommand() through setCommand(), setGenericCommand(), down to the actual key-value write in db.c. List every named hop in order, with file and line for each.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_case2_set_chain.md`):Full GT chain (docs/research/hard-benchmark/gt_case2_set_chain.md): processCommand -> lookupCommand -> (cmd->proc) setCommand(t_string.c:435) -> setGenericCommand -> lookupKeyWriteWithLink (existence check) -> setKeyByLink(db.c:754) -> [exists] dbSetValue + notifyKeyspaceEvent(overwritten) OR [!exists] dbAddByLink(db.c:460) -> dbAddInternal; then keyModified + notifyKeyspaceEvent(set). Score 3 requires naming setKeyByLink AND the exists/!exists branch split; score 2 stops at setGenericCommand without the branch.

**結果**:v3(before)= 3 分/$0.434/12t → v4(after)= 3 分/$0.413/18t

**v4 codex 判定理由**:Fully covers the required dispatch path and the write path, including lookupCommandLogic, call/cmd->proc, setCommand, setGenericCommand, lookupKeyWriteWithLink, and setKeyByLink. It clearly identifies the overwrite branch via dbSetValue and insert branch via dbAddByLink/dbAddInternal.

### WRQ-009 [wpa] [callback-indirect/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:struct wpa_driver_ops has 136 function-pointer fields. For the nl80211 driver backend (src/drivers/driver_nl80211.c, the wpa_driver_nl80211_ops struct literal), list EVERY field that is filled in, paired with the implementing function name. Do not stop partway through the struct literal.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_case1_driver_ops.txt`):Full GT (docs/research/hard-benchmark/gt_case1_driver_ops.txt): 96 of 136 fields filled. Score 3 requires all or nearly all 96 pairs correct; score 2 = found most but stopped before the end of the ~230-line struct literal (a common grep/Read failure mode); score 1 = only the first ~20-30 fields (matches the visible portion of one Read call).

**結果**:v3(before)= 2 分/$0.298/8t → v4(after)= 2 分/$0.302/8t

**v4 codex 判定理由**:Answer B is correct through the early Android section but is truncated at item 78 (`d...`) and does not provide the rest of the 96 GT pairs. It found most of the struct in order, but the answer is materially incomplete.

### WRQ-010 [redis] [callback-indirect/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:redis object types (e.g. OBJ_ENCODING_* handling in t_string.c / object.c) dispatch on obj->encoding via switch statements rather than a function-pointer ops table. Confirm whether redis's string type uses any function-pointer dispatch table (like moduleTypeMethods) versus wpa's ops-table pattern, and explain the difference in indirection style found.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-010.md`):VERIFIED 2026-07-07 — deliberate hallucination-trap question. Core object/string dispatch (object.c, t_string.c, t_list.c, t_hash.c) uses switch/if on o->encoding or o->type — NOT a function-pointer table (evidence: object.c:434,550,567,586,643-681,1290; t_list.c:452; t_hash.c:2078). A REAL function-pointer ops table exists only for Modules: RedisModuleTypeMethods (redismodule.h:1051) / moduleType (server.h:955), invoked via mv->type->free(...) in freeModuleObject (object.c:605), reached only via the distinct OBJ_MODULE case — core types never touch it. Rubric scores 0-1 for fabricating a fake…

**結果**:v3(before)= 3 分/$0.481/18t → v4(after)= 3 分/$0.453/18t

**v4 codex 判定理由**:Correct on the central distinction: built-in Redis types use switch/if dispatch with direct named calls, while only module objects use the function-pointer table. There are minor line/function citation slips, but the conceptual answer and module-only scoping match the GT.

### WRQ-011 [wpa] [data-structure/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find the definition of struct dl_list in src/utils/list.h and list every function in src/utils/list.c that operates on it (insert/remove/iterate).

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-011.md`):VERIFIED 2026-07-07 — THE QUESTION'S OWN PREMISE IS WRONG. src/utils/list.c does not exist in this repo (confirmed via find/git log --all/Makefile grep — never existed, not build-gated). struct dl_list (list.h:15-18: next/prev). All 6 operating functions (dl_list_init, dl_list_add, dl_list_add_tail, dl_list_del, dl_list_empty, dl_list_len) plus iteration macros (dl_list_for_each etc.) are static inline / macros defined directly in list.h, none in a nonexistent list.c. Independently spot-checked (find + grep -c "static inline" = 6): confirmed. Rubric treats correctly flagging the missing file a…

**結果**:v3(before)= 3 分/$0.216/7t → v4(after)= 3 分/$0.173/6t

**v4 codex 判定理由**:Fully correct: explicitly identifies the false premise about list.c, provides the struct definition, and enumerates all six inline functions plus the macro API in list.h. The extra note about ccodegraph/call graph behavior is not harmful.

### WRQ-012 [redis] [data-structure/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find the definition of the robj struct (or kvobj if robj is now an alias) and list which fields determine its reference-counting behavior.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-012.md`):VERIFIED 2026-07-07. Struct is `redisObject` (src/object.h:100-112); both `robj` and `kvobj` are currently plain typedef aliases of the SAME struct in this checkout (no separate kvobj type yet — distinguished only by the iskvobj:1 bitfield). Refcount-governing fields/constants: refcount (bitfield, object.c incr/decrRefCount), OBJ_SHARED_REFCOUNT (object.h:96, shared/immutable sentinel), OBJ_STATIC_REFCOUNT (object.h:97, stack-allocated sentinel, incrRefCount panics if retained), OBJ_FIRST_SPECIAL_REFCOUNT (threshold aliasing OBJ_STATIC_REFCOUNT). iskvobj gates which free path runs at refcount …

**結果**:v3(before)= 2 分/$0.281/10t → v4(after)= 3 分/$0.249/12t

**v4 codex 判定理由**:Correctly gives the struct location/layout and the fact that `robj` and `kvobj` are the same typedefed struct. It accurately explains `refcount`, `OBJ_SHARED_REFCOUNT`, `OBJ_STATIC_REFCOUNT`, `OBJ_FIRST_SPECIAL_REFCOUNT`, and mentions `iskvobj` only as affecting the deallocation path at refcount zero.

### WRQ-013 [wpa] [kconfig-build/L4]

**題目原文(verbatim,兩輪 harness 一字不差)**:wpa_supplicant has ~1985 `#ifdef CONFIG_*` conditional blocks. For CONFIG_SAE specifically, list every FUNCTION (not just file or line) whose compiled behavior depends on it, across the whole src/ tree. For each function, classify whether the ENTIRE function only exists under CONFIG_SAE ("whole"), or the function always exists but only PART of its body is conditional ("partial").

**GT 要點與評分標準**(完整版:`hard-benchmark/questions.jsonl(evaluation_notes)`):GT CORRECTED TWICE. Round 1 (2026-07-06, after the original A/B run): discovered the Makefile whole-file gate for src/common/sae.c (35 functions, wpa_supplicant/Makefile:241-243 `ifdef CONFIG_SAE ... OBJS += ../src/common/sae.o ... endif`) that the naive grep-based original GT (19 whole) had missed -- but ALSO wrongly folded in 5 functions from wpa_supplicant/sme.c, arriving at a mistaken 'true' whole-count of 54. Round 2 (2026-07-07, after running CodeGraph and cbm on this same question with Opus 4.8 as a third-party comparison): both third-party tools independently arrived at 49 whole (35 sa…

**結果**:v3(before)= 2 分/$0.664/17t → v4(after)= 3 分/$1.207/41t

**v4 codex 判定理由**:Matches the GT: 35 Makefile-gated `src/common/sae.c` functions plus 14 `ieee802_11.c` whole functions, and all 9 partial functions across the expected files. It also correctly excludes non-function struct-field blocks and out-of-scope/non-gated SAE-named helpers.

### WRQ-014 [redis] [kconfig-build/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find every place in the redis source tree gated by `#ifdef USE_JEMALLOC` or `#ifdef HAVE_BACKTRACE`, and report which SUBSYSTEM each belongs to (memory allocator vs crash/debug reporting).

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-014.md`):VERIFIED 2026-07-07. USE_JEMALLOC (memory-allocator subsystem): 13 files in src/ (zmalloc.c/h, sds.c, object.c, server.c, db.c, lazyfree.c, cluster_asm.c, eval.c, function_lua.c, script.c, syscheck.c, debug.c(3 sites)) — all confirmed by reading surrounding code, not filename-guessed. HAVE_BACKTRACE (crash/debug subsystem): all 15 occurrences confined to src/debug.c alone. Build-system effect found: src/Makefile has real ifeq blocks (lines 84-106, 301-305) deciding whether the whole external deps/jemalloc library gets built/linked — bigger than any single .c file, but does NOT conditionally ad…

**結果**:v3(before)= 1 分/$0.330/14t → v4(after)= 2 分/$0.253/9t

**v4 codex 判定理由**:Mostly correct on the USE_JEMALLOC inventory and subsystem classification across the expected 13 source files, including debug.c as allocator-related. Real gaps remain: it omits the GT-required Makefile build-system effect and undercounts/misstates HAVE_BACKTRACE occurrences.

### WRQ-015 [wpa] [include-dependency/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:Which .c files directly #include "eloop.h"? Give an exact count and confirm whether the count matches a transitive closure via any header that itself includes eloop.h.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-015.md`):VERIFIED 2026-07-07 — literal grep undercounts by half. Naive `#include "eloop.h"` grep = 59 files. TRUE count = 117: 58 more files use the alternate spelling `#include "utils/eloop.h"` (zero overlap with the 59), which resolves to the identical physical header because wpa_supplicant/Makefile sets `-I ../src` and `-I ../src/utils` unconditionally for every build (not behind any ifdef). Transitive closure is empty (no header itself includes eloop.h in either spelling), so the 117 direct includers ARE the complete dependent set — but only because there's no further transitive contribution, not b…

**結果**:v3(before)= 3 分/$0.470/15t → v4(after)= 3 分/$0.301/11t

**v4 codex 判定理由**:Answer B gives the correct true count of 117 by including both `"eloop.h"` and `"utils/eloop.h"`, and correctly states that no header includes `eloop.h`, so the transitive closure adds zero files. Minor formatting/count-list quirks do not undermine the core GT-required result.

### WRQ-016 [redis] [include-dependency/L1]

**題目原文(verbatim,兩輪 harness 一字不差)**:How many .c files directly #include "server.h"?

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-016.md`):VERIFIED 2026-07-07. Exact count: 70 .c files directly #include "server.h" under src/ (verified two ways: file-count and per-file occurrence-count, both = 70, no duplicates). Whole-repo search confirms deps/, tests/, modules/ contribute zero additional files — no real scope ambiguity. Full detail: gt_WRQ-016.md.

**結果**:v3(before)= 2 分/$0.200/7t → v4(after)= 3 分/$0.161/6t

**v4 codex 判定理由**:Gives the exact count of 70 and supports it with multiple checks: graph includers filtered to .c, SQL COUNT/DISTINCT COUNT, and a whole-repo grep. Although the deps/tests/modules point is not spelled out in those exact names, the whole-repo verification and matching count satisfy the full-credit intent.

### WRQ-017 [redis] [dataflow-lifetime/L4]

**題目原文(verbatim,兩輪 harness 一字不差)**:In src/t_string.c, every call to createStringObject/createStringObjectFromLongLong/createStringObjectFromLongDouble/createStringObjectFromLongLongForValue allocates a fresh object. For EACH such allocation site, determine whether the object is (a) locally freed via decrRefCount within the SAME function, or (b) its ownership is transferred elsewhere (e.g., handed to the database as the new value) and therefore has no local decrRefCount. List both categories separately.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_case4_lifecycle.md`):Full GT (docs/research/hard-benchmark/gt_case4_lifecycle.md): 5 locally-freed pairs (setGenericCommand, getexCommand, msetexCommand, increxCommand each create/decrRefCount a milliseconds_obj temp; lcsCommand creates/frees two comparison temps obja/objb) vs 3 ownership-transfer functions (incrDecrCommand, incrbyfloatCommand, increxCommand's 'new' value object -- these are handed to the key-write path and freed later, not in this function). Score 3 = correctly separates both categories; score 2 = finds all allocation sites but treats ownership-transfer sites as bugs/leaks or omits them; score 1 …

**結果**:v3(before)= 3 分/$0.443/14t → v4(after)= 3 分/$0.386/12t

**v4 codex 判定理由**:Fully matches the GT: all local frees are listed with the correct decrRefCount lines, and all new-value allocations are correctly classified as transferred to the DB with no local decrRefCount.

### WRQ-018 [wpa] [dataflow-lifetime/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:Find every os_malloc() call in src/utils/os_unix.c's callers within src/eap_common/ and confirm each has a matching os_free() on all exit paths (including error paths).

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-018.md`):VERIFIED 2026-07-07. Clarified scope: question means functions in src/eap_common/*.c calling os_malloc() (not os_unix.c's own internal calls, which are just the allocator's own implementation). Found 26 call sites across 8 files. Verdict: NO LEAKS anywhere — 14 are local alloc/free pairs (freed on both the internal-failure and normal-completion paths, incl. goto-based cleanup converging correctly), 3 are return-value ownership transfers (correctly left unfreed on success, freed on every internal error path), 7 are struct-field ownership transfers inside one function (ikev2_derive_sk_keys, ikev…

**結果**:v3(before)= 3 分/$0.941/20t → v4(after)= 3 分/$1.032/27t

**v4 codex 判定理由**:Fully consistent with the GT: 26 call sites across the expected functions, all error and success paths accounted for, including the keybuf cleanup and ikev2_free_keys() handling for the seven SK_* allocations.

### WRQ-019 [redis] [locking-rcu/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:bio.c spawns a background thread via pthread_create for bioProcessBackgroundJobs. List every piece of shared state (global variables or struct fields) this background thread reads or writes that the main thread also touches, and identify what synchronization primitive (if any) protects each.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-019.md`):VERIFIED 2026-07-07 — draft hint was half-wrong. bioInit() spawns 3 threads (BIO_WORKER_NUM=3, not 1), all running bioProcessBackgroundJobs. Shared state: bio_jobs[3] + bio_jobs_counter[7], guarded by bio_mutex[worker] (PER-WORKER, not per-job-type as the draft note claimed — 7 job types map onto only 3 workers); bio_comp_list guarded by a SEPARATE single mutex bio_mutex_comp (a common miss); job_comp_pipe[2] has NO mutex (safe via POSIX write-atomicity + happens-before at thread creation); three AOF-fsync status fields (server.aof_bio_fsync_status/errno, fsynced_reploff_pending) are redisAtom…

**結果**:v3(before)= 2 分/$0.460/10t → v4(after)= 3 分/$0.455/13t

**v4 codex 判定理由**:Covers all GT-required shared state and synchronization, including the per-worker mutex granularity, separate completion-list mutex, no-mutex pipe, redisAtomic fields, and immutable bio_cpulist. It slightly over-discusses job payload ownership transfer, but identifies it as having no independent concurrent sharing, so there is no material miss.

### WRQ-020 [wpa] [locking-rcu/N/A]

**題目原文(verbatim,兩輪 harness 一字不差)**:Does wpa_supplicant's core event loop (src/utils/eloop.c) use any locks, mutexes, or RCU-style synchronization for its timeout/socket registration lists?

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-020.md`):VERIFIED 2026-07-07 — trap question, draft hint confirmed correct with hard evidence. src/utils/eloop.c has zero pthread/lock/RCU/semaphore symbols (grep confirmed on all common patterns). Repo-wide: zero `pthread_*` symbols exist ANYWHERE in the checkout — no thread is ever spawned that could concurrently touch eloop's dl_list-based timeout/socket registration. Rubric explicitly ranks confident fabrication (inventing mutexes/RCU that don't exist) as the worst outcome (0), below a terse unsupported-but-correct 'no' (1), below a correct answer with partial evidence (2), full credit (3) requires…

**結果**:v3(before)= 2 分/$0.265/7t → v4(after)= 2 分/$0.173/6t

**v4 codex 判定理由**:Correct conclusion with relevant eloop.c evidence and no fabricated synchronization, but it does not provide the repo-wide pthread_create/pthread_* absence check required for a 3. Minor wording incorrectly implies socket tables are dl_lists, but the main answer remains substantially correct.

### WRQ-021 [wpa] [bug-localization/L3]

**題目原文(verbatim,兩輪 harness 一字不差)**:A user reports wpa_supplicant returning a generic 'scan failed' error from the nl80211 driver backend. Find the function(s) in src/drivers/driver_nl80211.c that construct scan-trigger failure return paths, and list the distinct conditions under which each returns an error for a scan request.

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-021.md`):VERIFIED 2026-07-07 — file-scope trap. In THIS checkout, src/drivers/driver_nl80211.c contains only ONE scan-related function, driver_nl80211_scan2 (line 7223-7228), a 3-line forwarding wrapper with zero error conditions of its own. The real scan-trigger logic (and its distinct error-return conditions: netlink-attribute build failures, P2P-probe rate-mask failures, kernel/netlink rejection with AP-mode-retry vs. immediate-failure sub-branches) lives in a SIBLING translation unit, src/drivers/driver_nl80211_scan.c — confirmed at the build-system level (drivers.mak lists driver_nl80211_scan.o as…

**結果**:v3(before)= 3 分/$0.401/13t → v4(after)= 3 分/$0.407/15t

**v4 codex 判定理由**:It explicitly states the scope-trap result: driver_nl80211.c has only driver_nl80211_scan2, a pure forwarding wrapper with no independent error conditions, and the real logic is in the separate driver_nl80211_scan.c translation unit. The listed downstream conditions match the GT context without losing the file-scope distinction.

### WRQ-022 [redis] [bug-localization/L2]

**題目原文(verbatim,兩輪 harness 一字不差)**:A user sees a WRONGTYPE error when running SET on an existing key. Find where this specific error reply is constructed in the SET command path (not other commands).

**GT 要點與評分標準**(完整版:`hard-benchmark/gt_WRQ-022.md`):VERIFIED 2026-07-07. Plain SET on an existing key never WRONGTYPE-checks (overwrites unconditionally). WRONGTYPE from SET only fires via two option-gated branches inside setGenericCommand (t_string.c:87), both reachable only when command_type==COMMAND_SET: (A) the GET option, via getGenericCommand's checkType call at t_string.c:467; (B) the IFEQ/IFNE/IFDEQ/IFDNE options, direct inline checkType call at setGenericCommand:117-119. Both terminate in the shared helper checkType() (object.c:884-891), whose line object.c:887 (addReplyErrorObject(c,shared.wrongtypeerr)) is the actual construction sit…

**結果**:v3(before)= 3 分/$0.327/10t → v4(after)= 3 分/$0.290/11t

**v4 codex 判定理由**:Fully correct per GT: it distinguishes SET-specific call sites from the shared helper, includes both option families, notes ordinary SET has no checkType path, and pinpoints object.c:887 as the reply construction call.



## 附錄 B:codex 判定 prompt 模板原文

以下為 v3/v4 兩輪共用的評分 prompt 模板(`v4-analysis/score_v4.py` 的
`build_prompt`;v3 版唯一差異是 ccodegraph 槽取 v3 答案)。`{...}` 為逐題
代入的變數;輸出用 `--output-schema` 強制為每臂 `{score: 0-3, justification}`
的 JSON(schema 檔:`v3-analysis/score_schema.json`)。執行方式:
`codex exec --skip-git-repo-check --sandbox read-only --output-schema <schema>
--output-last-message <out> "<prompt>"`。

```text
You are an independent grader for a code-navigation benchmark. You are
NOT the one who built the ground truth or ran the agents being graded — grade
strictly from the evidence given below, and be skeptical of confident-sounding
but unverifiable claims.

## Question ({qid})
{question}

## Evaluation notes (from GT construction, includes scoring guidance)
{evaluation_notes}

## Full GT reference document
{gt_document, first 6000 chars}

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

**協議說明**:v4 重評分刻意沿用 4-slot 形狀、只替換 ccodegraph 槽(其餘三臂
用 v3 原答案當錨點),讓兩輪的評分基準最大程度可比;副產品是錨定臂的分數
重測讓我們直接量測了 grader 噪音(§6)。
