# R4 驗收 v3:硬題全題庫(22 題)× 4 工具(Sonnet 5)、wpa 真實 build、codex 獨立複核、Token 熱點分析

> 動機:使用者看完 v2 報告(4 題 × 4 工具 × Opus 4.8,見 `llm-ab-v2-hard-cases.md`)
> 後,要求把實驗規模大幅擴大:① headless 模型從 Opus 4.8 換成 **Sonnet 5**;
> ② 從 4 題擴大到題庫**全部 22 題**;③ wpa 也要有**真實** compile_commands.json
> (不再只有 redis);④ 用**另一個 codex**(非 Claude)獨立複核結果、整理數據;
> ⑤ 最終報告要涵蓋**所有工具的比較**;⑥ 分析目的明確聚焦「Token 耗在哪裡、
> 怎麼減少」,並要求 session transcript 分析,而不只是看 usage 欄位的總數字。
> 使用者也明確要求「需要分段」——這輪是 22 題 × 4 工具 = **88 次 headless 呼叫**,
> 規模是 v2 輪(16 次)的 5.5 倍,實際執行時也真的因為背景任務被系統中斷了 5 次,
> 全靠 harness 的 resume 機制(跳過已完成的組合)才順利跑完,細節見下方方法論。

## 目錄

1. [方法論](#方法論)
2. [wpa 真實 build:方法與已知限制](#wpa-真實-build方法與已知限制)
3. [18 題新 GT 建構](#18-題新-gt-建構)
4. [結果總表:22 題 × 4 工具](#結果總表22-題--4-工具)
5. [Token 熱點分析](#token-熱點分析)
6. [逐題挖出的意外發現](#逐題挖出的意外發現)
7. [v2 vs v3:模型差異(Opus 4.8 vs Sonnet 5)](#v2-vs-v3模型差異opus-48-vs-sonnet-5)
8. [誠實結論](#誠實結論)
9. [限制](#限制)

## 方法論

**模型**:這輪全部 88 次 headless 呼叫統一用 `--model claude-sonnet-5`
(v2 的 10 次 + 8 次共 18 次其實跑的是 Opus 4.8,詳見 v2 報告的模型落差說明;
這次使用者明確要求換回 Sonnet,不再意外用錯模型)。

**4 個對照組**(這次不再區分 ccodegraph 的合成/真實 DB 兩臂,統一用真實 DB):

- **none**:只能用 shell 指令(grep/awk/sed/cat/find/Read),不用任何知識圖工具。
- **ccodegraph**:本專案主角,這次兩個 repo 都用**真實** compile_commands.json
  建圖(redis 沿用既有 bear 產出的 357 條真實記錄;wpa 這次新建置,見下節)。
- **codegraph**:第三方工具(colbymchenry/codegraph,tree-sitter)。
- **cbm**:第三方工具(win4r/codebase-memory-mcp-pro fork,tree-sitter)。

隔離手法沿用 v2:`git archive HEAD` 乾淨複本 + `--setting-sources project`
跳過使用者全域 skill。harness:`tools/run_hard_ab_v3.py`(基於
`run_hard_ab.py`/`run_hard_ab_thirdparty.py` 改寫,新增**跨執行的
resume 機制**——每次呼叫前檢查 `summary.json` 裡是否已有該 (題號,工具)
組合的成功紀錄,有就跳過)。

**分段執行的實際情形**:22 題分成 6 段(每段 4-5 題,對應 16-20 次呼叫)依序
執行。過程中背景任務被系統中斷(非我主動停止)**5 次**,每次都靠 resume 機制
接著跑,沒有重複燒錢在已完成的組合上——這正是 harness 設計 resume 機制的
價值所在,也印證使用者「需要分段」的判斷是對的,這個規模的實驗本來就該假設
會被中斷。**最終 88 次呼叫全部 `rc=0`,零失敗**,總花費 **$28.00**。

**cbm 隔離修正**:v2 報告記錄過 cbm 曾在 WRQ-009 意外用 `CBM_BIN` 的絕對路徑
拼出 `.../cbm-fork/../` 跳出乾淨複本。這次 prompt 明確加了一句「唯一該讀的
原始碼在你目前工作目錄,cbm 執行檔路徑不是原始碼位置的線索」,88 次執行裡
沒有再觀察到同樣的路徑逃逸。

**評分**:不再由我一人球員兼裁判——**用 `codex exec`(OpenAI Codex CLI,
非 Claude)對全部 22 題獨立評分**,每題給 codex:題目原文、GT 檔案內容/
`evaluation_notes`、以及 4 個 arm 的完整原始答案,要求用 `--output-schema`
輸出結構化 JSON(每個 arm 一個 0-3 分 + 一段理由),codex 完全不知道我對
任何一題的既有想法。過程中 codex 的評分意外抓到一個我自己 GT 建構時的真錯誤
(WRQ-002,見下方逐題發現),已修正並重新計分。

## wpa 真實 build:方法與已知限制

使用者明確要求「花時間先把 wpa 真實建置跑起來」,而不是繼續沿用合成 DB。
**關鍵可行性問題**:`src/drivers/driver_nl80211.c` 直接 `#include <linux/
rtnetlink.h>`、`<linux/errqueue.h>` 等 **Linux 核心 UAPI header**——這些
在 macOS 上根本不存在(不是裝 `libnl` 就能解決,libnl 只是使用者空間函式庫,
核心 header 不會因此出現)。這代表 wpa 的 nl80211 driver backend **在這台
macOS 機器上物理上編不出來**,任何「wpa 真實 compile DB」都不可能涵蓋
`driver_nl80211.c`。

Linux-only header 只外洩到 5 個檔案(`driver_nl80211.c`、`driver_roboswitch.c`、
`ap/iapp.c`、`ap/vlan_init.c`、`ap/vlan_util.c`),其餘都是可攜 C 碼。實際做法:

1. `.config` 設 `CONFIG_DRIVER_WIRED=y`(關掉 nl80211/roboswitch)、
   `CONFIG_AP=y`、`CONFIG_SAE=y`、`CONFIG_CTRL_IFACE=y`、`NEED_AP_MLME=y`
   (手動開,因為原本只有 nl80211/hostap driver 會自動設這個變數)、
   OpenSSL 路徑指到 homebrew 的 `openssl@3`。
2. `bear -- make -j4 -k`(best-effort,`-k` 讓 make 略過個別編譯錯誤繼續跑—
   `deps/crypto_openssl.c` 因為這個 checkout 較舊、直接存取 OpenSSL 3.x 已經
   opaque 的內部 struct 欄位而編譯失敗,這是版本不相容,不是我們的設定問題,
   不影響其他獨立檔案的編譯)。
3. 分三輪跑(`bear --append`)才湊齊 WRQ-013 需要的全部 8 個檔案——第一輪
   缺 `ieee802_11.c`/`ctrl_iface_ap.c`(需要 `NEED_AP_MLME`/`CONFIG_CTRL_IFACE`
   這兩個沒有預設值的變數,原本只有 nl80211/hostap driver 會自動設),補上後
   第三輪才拿到完整覆蓋。

**最終覆蓋:90 個檔案有真實 compile command**(含 `-DCONFIG_SAE`、`-DCONFIG_AP`
等正確旗標),放在 repo 根目錄 `compile_commands.json`,`ccodegraph.py` 的
root 偵測邏輯自動撿到,confidence 提升到 0.95。**已確認的限制**:
`driver_nl80211.c` 不在這 90 個檔案裡——WRQ-009(nl80211 driver ops 欄位列舉)
這題的 ccodegraph arm 仍只能用 synthesized fallback(confidence 0.93)對這個
特定檔案,這是誠實記錄的已知限制,不是疏漏。

## 18 題新 GT 建構

題庫原本只有 4 題(WRQ-008/009/013/017)有 GT(v2 輪真跑的那 4 題)。這次擴大
到全部 22 題,代表另外 18 題都要重新建 GT。做法:每題派一個獨立 agent 直接對
真實原始碼(唯讀)做 grep/ctags/cscope/Read 交叉核對,並明確要求:

- 檢查題目文字本身的範圍限定詞(這是 v2 輪 WRQ-013 兩輪更正學到的教訓)
- 檢查 build 系統層級的效果(Makefile `ifdef`/`OBJS +=`),不只看原始碼層級
  的 `#ifdef`
- 用至少兩種獨立方法交叉驗證任何計數/列舉結果,再定案

18 個 agent 平行(分批)執行,**每一個都獨立找到至少一項真實的、非顯而易見的
修正**,例如(完整清單見各題 GT 檔案與 `questions.jsonl`):

- **WRQ-003**:`struct wpa_driver_ops` 實際有 **142** 個函式指標欄位,不是
  到處沿用的「136」(這個錯誤數字甚至就寫在 WRQ-009 已執行題目的原題文字裡,
  從沒被獨立驗證過)。
- **WRQ-011**:題目問的 `src/utils/list.c` **根本不存在**——`dl_list` 的所有
  操作都是 `list.h` 裡的 header-only inline 函式/巨集。
- **WRQ-015**:字面 grep 只找到 59 個檔案,真實數字是 **117**——58 個檔案用
  `#include "utils/eloop.h"` 這個替代拼法(因為 Makefile 無條件加了
  `-I ../src/utils`,兩種寫法解析到同一個檔案)。
- **WRQ-019**:共享狀態是**每個 worker**(3 個執行緒)各自的鎖,不是原始草稿
  假設的「每種 job type」(7 種);另外還有一個獨立的完成佇列鎖沒被草稿提到。
- **WRQ-021**:題目問的 `driver_nl80211.c` 裡其實只有一個 3 行的轉呼叫包裝
  函式——真正的 scan-trigger 錯誤建構邏輯在另一個檔案 `driver_nl80211_scan.c`
  (build 系統層級證實是獨立編譯單元,不是 `#include`)。

這次沒有另外派 18 個「對抗複核」agent 重跑一遍——鑑於每個第一輪 agent 都已經
內建至少兩種獨立交叉驗證方法,並且對兩個最意外的發現(WRQ-003 的 142、
WRQ-011 的檔案不存在)我自己也用 `awk`/`find` 直接複驗確認無誤,判斷這個
第一輪的嚴謹度已經足夠,把「第二個獨立 agent」的角色改為**用 codex 對全部
22 題的最終答案評分**(見下)——這比對 GT 本身重跑一次驗證更能捕捉問題,
事實也證明有效(見 WRQ-002 的 hiredis 發現)。

## 結果總表:22 題 × 4 工具

評分:codex 獨立打分(0-3),與我在 GT 建構/事後核對時的判讀交叉檢查過至少
3 個最大分歧的題目(見下方「逐題挖出的意外發現」)。

| 題號 | none | ccodegraph | codegraph | cbm |
|---|---|---|---|---|
| WRQ-001 | 3 | 3 | 3 | 3 |
| WRQ-002 | 3† | 3† | 3† | 3† |
| WRQ-003 | 3 | 3 | 3 | 3 |
| WRQ-004 | 3 | 3 | 3 | 3 |
| WRQ-005 | 3 | 3 | 3 | 3 |
| WRQ-006 | 3 | 3 | 3 | 2 |
| WRQ-007 | 1 | 3 | 3 | 3 |
| WRQ-008 | 3 | 3 | 3 | 3 |
| WRQ-009 | 2 | 2 | 2 | 2 |
| WRQ-010 | 3 | 3 | 3 | 3 |
| WRQ-011 | 3 | 3 | 3 | 3 |
| WRQ-012 | 2 | 2 | 2 | 2 |
| WRQ-013 | 1 | 2 | 1 | 3 |
| WRQ-014 | 1 | 1 | 2 | 1 |
| WRQ-015 | 2 | 3 | 3 | 2 |
| WRQ-016 | 2 | 2 | 3 | 3 |
| WRQ-017 | 3 | 3 | 3 | 3 |
| WRQ-018 | 3 | 3 | 3 | 2 |
| WRQ-019 | 3 | 2 | 2 | 2 |
| WRQ-020 | 2 | 2 | 2 | 2 |
| WRQ-021 | 2 | 3 | 3 | 3 |
| WRQ-022 | 3 | 3 | 2 | 3 |
| **合計 /66** | **54** | **58** | **58** | **57** |
| **平均** | **2.45** | **2.64** | **2.64** | **2.59** |

† WRQ-002 原始 codex 評分是 4 個 arm 都給 2 分(理由:全部 4 個 arm 都額外
提到 `deps/hiredis/hiredis.c` 有一個同名 `createStringObject`,codex 依照
我當時的 GT——GT 說「沒找到這個衝突」——判定這是需要扣分的可疑宣稱)。
**核對後發現是我的 GT 錯了**:`deps/hiredis/hiredis.c:125` 真的有一個
`static`、不同簽名的同名函式(vendored 的 hiredis client library 內部的
RESP 解析輔助函式,無關 redis-server 的物件系統)。**四個 arm 都正確、獨立
抓到這個真實但隱蔽的符號碰撞**——已更正 GT(`gt_WRQ-002.md`)並重新計分為
3 分。這是本輪除了 token 分析之外,codex 獨立複核**最直接的價值展示**:
連一題看似簡單的 L1 符號查找,GT 建構時都可能漏看一個真實的邊界情況。

**整體正確性**:三個知識圖工具(ccodegraph、CodeGraph、cbm)都以個位數幅度
贏過純 grep 基準線(58/58/57 vs 54,滿分 66),差距不大但方向一致且穩定
(v2 輪 4 題規模太小看不出這個穩定但微小的優勢;22 題規模才顯現出來)。
三個工具彼此之間幾乎打平,沒有哪一個在整體正確性上明顯勝出。

## Token 熱點分析

這是使用者最明確要求的分析目的:「檢查 Token 耗在什麼地方,並提出如何減少
Token 的方案」。方法:對全部 88 份 session transcript,逐一取出每個
`tool_use`→`tool_result` pair,記錄工具名稱、標準化後的指令特徵(grep/
`ccodegraph:explore`/`codegraph:node`/`cbm:query_graph` 等)、以及回傳內容的
位元組數(這才是真正塞回 context、燒 token 的東西,不是呼叫次數本身)。

### 整體:哪個工具實際上更貴?(意外的發現)

| Arm | 總花費 | 總分/66 | **每一分正確性的花費** | 平均每題花費 |
|---|---|---|---|---|
| none | $5.77 | 54 | **$0.107** | $0.262 |
| ccodegraph | $7.99 | 58 | **$0.138** | $0.363 |
| codegraph | $6.86 | 58 | **$0.118** | $0.312 |
| cbm | $7.37 | 57 | **$0.129** | $0.335 |

**這是本輪最違反直覺的發現**:ccodegraph 是這 4 個 arm 裡**總花費最高**、
**每一分正確性成本也最高**的一個——比純 grep 基準線貴 38%,比另外兩個第三方
工具也貴。純 grep 基準線反而是**最省錢**的選項(雖然正確性也最低)。這不是
「工具沒用」,是「這一版工具用起來比預期貴」,原因如下。

### tool_result 位元組數:Read 是所有工具共同的最大單一元凶

| 工具 | Read 呼叫次數 | Read 總位元組 | 佔該工具 tool_result 總量比例 |
|---|---|---|---|
| none | 26 | 116,816 | 39% |
| ccodegraph | 31 | 158,366 | 32% |
| codegraph | 33 | 141,375 | 36% |
| cbm | 51 | 153,215 | 46% |

**不管用不用圖工具,Read 原始碼檔案永遠是最大的單一 token 來源**——這代表
「精確答案需要讀原始碼本體」這件事,任何圖工具都沒辦法完全取代,圖只能幫忙
**定位**該讀哪裡,讀了之後那段文字本身的 token 成本是省不掉的。cbm 的 Read
佔比最高(46%)且次數最多(51 次)——因為 cbm 的圖查詢在 C 專案上普遍幫不上忙
(見下),被迫更依賴 grep 定位 + Read 驗證這個組合。

### ccodegraph 貴在哪:探索性呼叫、`cd`、以及沒用上的 `--help`

拆解 ccodegraph arm 的 tool_result 位元組數來源(前幾名):

```
Read                 31 次   158,366 bytes
ccodegraph:explore   16 次    70,495 bytes  (平均每次 4,406 bytes)
ls                    7 次    55,542 bytes  (平均每次 7,935 bytes——異常肥大)
cd(其他分類)         32 次    54,405 bytes
ccodegraph:callers    1 次    27,862 bytes
ccodegraph:sql       24 次    26,278 bytes
ccodegraph:--help     7 次    15,246 bytes  ← 純粹是浪費
ccodegraph:status     6 次     7,288 bytes
ccodegraph:schema    12 次     6,290 bytes
```

三個具體發現:

1. **`ccodegraph:--help` 出現 7 次**——agent 在使用某個子指令前臨時查用法,
   代表 SKILL.md 目前給的指令範例不夠完整,agent 需要現查語法。這是**純浪費**
   的 token,而且完全可避免:把常用子指令(`explore`/`sql`/`callers`/
   `callees`)的完整範例語法直接寫進 SKILL.md,不要讓 agent 猜。
2. **`ls` 呼叫平均 7,935 bytes**——遠高於其他工具的 `ls`(codegraph 只有
   833 bytes/次),推測是 agent 在乾淨複本的根目錄用 `ls -la` 之類的完整
   列表,而不是針對性地找特定檔案。
3. **`cd` 相關指令 32 次、5.4 萬 bytes**——這通常是 shell 指令本身沒有實質
   輸出但仍算進 tool_result 的固定 overhead(prompt/echo),累加起來也不小。

**改善方向(這是使用者要的產出,不寫進程式碼,留給 SKILL.md 下次修訂時採用)**:

1. **SKILL.md 應該內嵌每個常用子指令的完整呼叫範例**(不只是列出指令名稱),
   讓 agent 不需要用 `--help` 現查語法——直接消除這 7 次、1.5 萬 bytes 的
   純浪費呼叫。
2. **教 agent 用 `explore`/`sql` 時帶明確的過濾/裁切條件**(例如
   `LIMIT`、`head -N`),而不是預設拿全部結果——`explore` 平均每次
   4,406 bytes,是這次除了 Read 外最貴的單一指令類型,值得優化。
3. **CodeGraph 的 `node` 指令預設帶完整原始碼片段**——如果只需要呼叫關係,
   優先用 `callers`/`callees`(更精簡),只在最後一步才用 `node` 看程式碼本體。
4. **cbm 的 Cypher 查詢應該教 agent 加 `LIMIT`**——cbm 的 `query_graph`
   呼叫 40 次、平均 933 bytes,不算誇張,但 51 次 Read(遠高於其他工具)代表
   cbm 的圖查詢常常查不到想要的東西,被迫退回 Read——這其實是「cbm 對 C
   語言的圖建模能力不足」這個更根本問題的 token 面表現,不是單純的查詢語法
   問題,詳見 v2 報告已記錄的「cbm CALLS 邊在 C 專案上~99%掛在檔案而非函式」
   限制,這次 22 題規模的數據與那個結論完全一致。
5. **「花更多 token 不保證換到更高分」這件事本身值得寫進 SKILL 的風險章節**——
   ccodegraph 這次每一分正確性的成本比純 grep 基準線貴 38%,但整體正確性只贏
   4 分(58 vs 54,滿分 66)。要讓 ccodegraph 真的物有所值,上面 1-2 點的
   token 減量比追求更高分更優先。

## 逐題挖出的意外發現

**WRQ-007(redis caller-callee)——本輪 none 輸最慘的一題**:純 grep 只拿到
1 分,三個工具都拿滿分 3 分。這題要求「找出 t_string.c 裡所有會呼叫
setKeyByLink() 的函式(直接或先呼叫 setGenericCommand())」——一個真正需要
多跳追蹤的問題,grep 臂容易漏掉間接路徑,三個圖工具都用某種形式的查詢/交叉
比對過(codex 的評分理由確認了這點)。這是本輪少數「工具真的有幫助」的
明確案例。

**WRQ-013(wpa CONFIG_SAE)——這輪 Sonnet 5 比 v2 輪 Opus 4.8 表現更差**:
none/codegraph 只拿 1 分(漏掉 Makefile 整檔閘控的 sae.c,35 個函式)、
ccodegraph 拿 2 分(注意到 build 系統依賴但沒把 sae.c 正式列入答案、數量算
成 34 而非 35)、只有 cbm 拿到滿分 3 分。**對照 v2 輪**:當時用 Opus 4.8,
ccodegraph 的兩臂(A/B)都獨立抓到了這個 Makefile 機制。這次用 Sonnet 5,
4 個 arm 裡有 3 個沒抓到——這是一個具體的、可觀察的**模型能力差異**證據:
「讀 Makefile 而不只讀原始碼」這個推理深度,Opus 4.8 比 Sonnet 5 更穩定地
做到。

**WRQ-014(redis USE_JEMALLOC/HAVE_BACKTRACE)——本輪整體表現最弱的一題**:
none/ccodegraph/cbm 都只拿 1 分,codegraph 拿 2 分。codex 的評分理由指出
所有 arm 都只找到 zmalloc.c/debug.c 裡「顯而易見」的 4 個位置,漏掉了 GT
要求的、分布在 src/ 其他檔案(object.c、server.c、db.c、lazyfree.c、
cluster_asm.c、eval.c、function_lua.c、script.c、syscheck.c 等)裡更隱蔽的
USE_JEMALLOC 使用,以及 Makefile 層級「整個 jemalloc 依賴函式庫要不要編譯/
連結」這個更大範圍的 build 效果。這是本輪唯一一題**沒有任何 arm 表現良好**
的案例,顯示這類「巨集使用分散在很多不起眼位置」的題型,對所有現有方法
(圖工具或 grep)都是硬骨頭。

**WRQ-019(redis bio.c 併發模型)——本輪唯一 none 贏過所有工具的一題**:
none 拿滿分 3 分,三個工具都只拿 2 分。codex 的評分理由顯示:三個工具各自在
答案裡多加了一項 GT 明確排除的項目(例如把 `bio_worker_title[]` 誤列為
共享狀態),而純 grep 的答案反而沒有這個過度延伸的問題。這是一個提醒:**圖
工具讓 agent 傾向給出更詳盡、結構化的答案(例如表格列出更多項目),但條目
越多,踩到 GT 排除項的機率也越高**——多不一定準。

## v2 vs v3:模型差異(Opus 4.8 vs Sonnet 5)

v2 輪(4 題)全部用 Opus 4.8(意外,非本意),v3 輪(22 題)使用者明確要求
全部改用 Sonnet 5。兩輪的 4 個原始真跑題(WRQ-008/009/013/017)在兩種模型下
都測過,可以直接對照:

| 題號 | Opus 4.8(v2) | Sonnet 5(v3,本輪) |
|---|---|---|
| WRQ-008 | A=3, B=3(ccodegraph) | none=3, ccodegraph=3 |
| WRQ-009 | A=3(算術誤), B=3 | none=2, ccodegraph=2 |
| WRQ-013 | A=3†, B=3†(更正後) | none=1, ccodegraph=2 |
| WRQ-017 | A=3, B=3 | none=3, ccodegraph=3 |

WRQ-013 是兩輪之間**唯一出現方向性差異**的題目——Opus 4.8 兩臂都抓到
Makefile 整檔閘控,Sonnet 5 只有 ccodegraph 部分抓到(2 分,none 只有 1 分)。
WRQ-009 也有小幅下降(3→2,兩輪都卡在同一種「加總算術」錯誤,但 v3 輪的
codex 評分對這類錯誤給分更嚴格,不能簡單類比)。其餘題目兩種模型表現一致。
**樣本數只有 4 題,不能斷言「Sonnet 5 整體比 Opus 4.8 弱」,但這確實是這輪
唯一觀察到的、跟模型能力(而非工具)直接相關的分數差異**,值得未來如果做
N=3+ 正式重跑時特別關注 WRQ-013 這類「需要讀 build 系統檔案而非只讀原始碼」
的題型。

## 誠實結論

1. **三個知識圖工具都以個位數幅度贏過純 grep 基準線,但沒有一個工具彼此
   拉開差距**——22 題規模下,ccodegraph/codegraph 都是 58/66,cbm 57/66,
   none 54/66。這比 v2 輪(4 題,幾乎打平)更能顯現「有工具比沒工具好」的
   穩定但微小的效果,但**工具之間彼此打平**這件事在更大樣本下依然成立。
2. **ccodegraph 這次是「贏但贏得不便宜」**——每一分正確性的成本比純 grep
   貴 38%,是 4 個 arm 中最貴的。這次的 token 熱點分析明確定位了原因
   (`--help` 查詢浪費、`explore` 平均單次成本高、`ls`/`cd` 開銷),都是
   SKILL.md 教學層面可以改善的,不需要動 schema。
3. **Read 原始碼是所有工具共同、不可避免的最大 token 來源**——圖工具能幫的
   是「定位去哪裡讀」,讀了之後那段文字的成本省不掉。這代表未來優化的重點
   應該是「減少不必要的 Read」(教 agent 更精準地只讀需要的行號範圍),而不是
   幻想圖工具能完全取代讀原始碼這件事。
4. **codex 獨立複核直接抓到我自己的一個 GT 錯誤**(WRQ-002 的 hiredis 符號
   碰撞)——證實使用者要求「用另一個 codex 檢查結果」這個方法論本身是對的,
   自己既出題、又建 GT、又評分,確實容易一步錯、步步錯。
5. **模型選擇本身可能比工具選擇更影響某些題型的表現**——WRQ-013 這題在
   Opus 4.8 下兩臂都答對,在 Sonnet 5 下 3/4 個 arm 都沒抓到同一個機制。
   這提醒:benchmark 結論必須註明用的是哪個模型,換模型不能假設結論一樣
   會成立。

## 限制

- **N=1**:22 題全部只跑一次,沒有重複驗證變異數(同 v2 輪已記錄的限制,
  規模擴大但這個方法論限制沒變)。
- **codex 評分本身也是單一模型的單次判斷**,不是多模型多數決;雖然抓到了
  WRQ-002 的真錯誤,但 codex 的評分標準本身沒有經過交叉驗證,可能在某些
  題目上偏嚴或偏鬆(例如 WRQ-002 一開始把「正確發現的符號碰撞」誤判為扣分項,
  正是因為 codex 完全信任了我給的、有錯的 GT)。
- **wpa 的真實 compile DB 仍有已知缺口**(`driver_nl80211.c` 因 macOS 缺
  Linux 核心 header 而無法涵蓋)——WRQ-009/WRQ-021 這兩題涉及該檔案,
  ccodegraph arm 對這個特定檔案仍是 synthesized fallback,不是真正的
  「全 wpa 都測到真實 DB」。
- **v2 vs v3 模型對照只有 4 個資料點**(WRQ-008/009/013/017),不足以做
  統計顯著的模型比較,只能記錄為「值得未來關注」的觀察,不是結論。
- **Token 熱點分析用的是 tool_result 的位元組數,不是真正計費的 token 數**
  (兩者高度相關但不完全相等,byte→token 的實際比例依內容而異);用 usage
  欄位裡的 input_tokens/output_tokens/cache_* 才是真正計費的數字,byte 分析
  只用來定位「哪一類指令」是熱點,不是精確的 token 會計。
