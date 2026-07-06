# R4 驗收 v2:硬題 A/B(真 Claude Code headless,N=1,2026-07-06;Arm C + 第三方工具對照於 2026-07-07 補做)

> 動機:使用者對第一輪 5 題 A/B(`llm-ab.md`)的反饋——「太簡單,認不出差別」。
> 仿 `linux-kernel-navigation-benchmark` 的分類法為 wpa_supplicant/redis 出了
> 22 題難題庫(`docs/research/hard-benchmark/`,12 類適配、L1–L4),挑 4 題
> 最難的(L3/L4,涵蓋多跳呼叫鏈、136 欄位大型 ops table、條件編譯函式層級歸戶、
> 資料流生命週期)用真 **Claude Code headless mode** 跑,不是 codex。看完
> 這輪結果後,使用者又提出 5 個常見問題(GT 定義/來源、題目原文不清楚、
> 三方 compile DB 對照、N=3 的意義、能否從證據歸納改進方向而不寫死程式碼)
> 與一個假設(ccodegraph 是不是被當 grep 用),下方逐一補上回答,並新增
> Arm C(redis 真實 compile_commands.json)與**第三方工具(CodeGraph、cbm,
> 統一用 Opus 4.8)對照實驗**——後者意外發現一個更重要的事:WRQ-013 的 GT
> 在前一輪的「更正」本身就是錯的(算漏了題目自己的範圍限定詞),已在本次
> 補做時第二次更正並誠實記錄。

## 常見問題(先回答,再看方法論)

### Q:「GT」是什麼?每題的 GT 從哪來?

GT = **Ground Truth**,是這份報告用來打分數的「正確答案」,不是任何 LLM 或
第三方文件產生的,而是**我在跑 agent 之前,自己對照真實原始碼手工建構**的:
用 `grep`/`ctags`/`cscope`,有時也直接用 ccodegraph 查圖,逐行讀函式本體、
逐一核對呼叫點,把「這題正確答案應該長什麼樣子」寫成獨立檔案(見下表)。
GT 建好之後才讓兩臂的 agent 開始作答,評分時我拿 agent 的答案與 GT 逐項核對
(0–3 分,標準見 `taxonomy.md`),不假手第二個 LLM 當裁判。

**重要的誠實揭露**:這次過程中發現,GT 本身也可能不完整、也可能被我自己
「更正」錯——WRQ-008 兩臂都追得比我的原始 GT 更深一層;WRQ-013 更曲折:
我最初的 GT 漏算了 Makefile 整檔閘控的一整個檔案,事後「更正」時又多算了
一個題目範圍外的檔案(`wpa_supplicant/sme.c`,不在題目指定的 `src/` 樹裡),
直到 2026-07-07 補做第三方工具對照才發現這個更正本身是錯的。這代表
「GT 是絕對正確答案」這個假設在 L4 難度下本身就要打折扣,連評分者反覆核對
也可能出錯,詳見下方「逐題詳情」與「誠實結論」第 3 點。

每題 GT 的來源檔案:

| 題號 | GT 檔案 | 建構方式 |
|---|---|---|
| WRQ-008 | `docs/research/hard-benchmark/gt_case2_set_chain.md` | 手動追蹤呼叫鏈,逐跳對照 `t_string.c`/`db.c`/`kvstore.c` 原始碼行號 |
| WRQ-009 | `docs/research/hard-benchmark/gt_case1_driver_ops.txt` | 直接讀 `driver_nl80211.c` 的 `wpa_driver_nl80211_ops` struct literal,逐欄位記錄 field→function |
| WRQ-013 | `docs/research/hard-benchmark/questions.jsonl`(WRQ-013 條目的 `evaluation_notes`,含 `_gt_correction_note` 兩輪更正記錄) | 先 grep `#ifdef CONFIG_SAE`,事後發現需另外核對 `Makefile` 的 `OBJS +=` 整檔閘控(第一輪更正);第二輪更正把誤加的題目範圍外檔案(`sme.c`,不在 `src/` 樹裡)排除 |
| WRQ-017 | `docs/research/hard-benchmark/gt_case4_lifecycle.md` | 用 ccodegraph SQL 查詢 + 逐行讀 `t_string.c` 核對每個配置點的釋放/轉移路徑 |

### Q:題目到底在問什麼?(逐題完整原文)

下面是 4 題的**完整英文原題**(直接來自 `tools/run_hard_ab.py` 的 `CASES`,
兩臂拿到的問題文字一字不差,只是 A 臂加了「只能用 shell 指令」的限制、
B 臂加了「請用 ccodegraph.py」的提示):

| 題號 | 分類/難度 | 完整題目原文 |
|---|---|---|
| WRQ-008 | entry-path / L3 | "Trace the full call path from Redis command dispatch to the lowest-level database write for the SET command: from lookupCommand()/processCommand() through setCommand(), setGenericCommand(), down to the actual key-value write in db.c. List every named hop in order, with file and line for each." |
| WRQ-009 | callback-indirect / L3 | "struct wpa_driver_ops has 136 function-pointer fields. For the nl80211 driver backend (src/drivers/driver_nl80211.c, the wpa_driver_nl80211_ops struct literal), list EVERY field that is filled in, paired with the implementing function name. Do not stop partway through the struct literal." |
| WRQ-013 | kconfig-build / L4 | "wpa_supplicant has ~1985 `#ifdef CONFIG_*` conditional blocks. For CONFIG_SAE specifically, list every FUNCTION (not just file or line) whose compiled behavior depends on it, across the whole src/ tree. For each function, classify whether the ENTIRE function only exists under CONFIG_SAE (\"whole\"), or the function always exists but only PART of its body is conditional (\"partial\")." |
| WRQ-017 | dataflow-lifetime / L4 | "In src/t_string.c, every call to createStringObject/createStringObjectFromLongLong/createStringObjectFromLongDouble/createStringObjectFromLongLongForValue allocates a fresh object. For EACH such allocation site, determine whether the object is (a) locally freed via decrRefCount within the SAME function, or (b) its ownership is transferred elsewhere (e.g., handed to the database as the new value) and therefore has no local decrRefCount. List both categories separately." |

(完整 22 題題庫、含未執行的 18 題,見 `docs/research/hard-benchmark/questions.md`。)

### Q:「N=3」是什麼意思?為什麼需要再做一次?

這輪每題**只跑了一次**(N=1)。「N=3」是指同一題、同一臂,**重複跑 3 次**、
取 3 次分數/token/耗時的分佈,而不是只看單一次的結果。原因是 LLM 的回答
本身有隨機性(即使問題一樣,每次探索路徑、用的指令數、甚至有沒有漏看某個
細節都可能不同)——這份報告裡最明顯的例子是 **WRQ-009**:A 臂只花了 3 個
turn 就答完,B 臂卻花了 8 個 turn,兩者分數卻打平。如果只跑一次就下結論
「A 比較快」,可能只是這次剛好運氣好/壞,並非穩定的能力差異。要讓
「B 平均比較快/比較準」這類結論站得住腳,理想上應該對同一題目重複跑
數次(業界常見取 N=3~5),看分數/耗時的**平均值與變異範圍**,而不是單次
結果。這是本輪報告在**方法論上明確承認的限制**,不是尚未修好的 bug。

## 方法論

**隔離**(避免混到舊的 ccq skill):`claude -p --setting-sources project` 只讀
專案層設定,完全跳過 `~/.claude/skills/ccq`(全域符號連結)。Arm A 拿到
`git archive HEAD` 的乾淨複本(零產物、零 skill);Arm B 拿到複本 + `ccodegraph.py`
+ 預先建好的圖(build + clink-import,不讓 agent 花 token 建圖)+ 專案層
`.claude/skills/ccodegraph/SKILL.md`。兩臂互不干擾、不動使用者全域設定
(harness:`tools/run_hard_ab.py`)。

**Prompt**:A =「只能用 shell 指令(grep/awk/sed/cat/find/Read)」;B =「用
`./ccodegraph.py`(圖已建好),必要時可搭配 sql 逃生口或少量 grep 覆核」。
兩臂都是「回答精簡但完整,不要省略細節列表」。N=1(單次先導,同前輪方法論)。

**評分**:0–3 分(taxonomy.md 標準),**我對照真實原始碼逐項核對**,不假手第二個
LLM 當裁判——過程中意外發現我**手工建的 GT 本身有兩處不完整**(見下),已誠實
記錄並更正,而不是悄悄採用對某一臂有利的版本。

## 意外插曲:準備 harness 時發現並修好一個真 bug(D15)

跑 Arm B 對 redis 的預建圖時,`build` 100% 重現失敗:cscope 對 `deps/jemalloc/
src/ctl.c` 裡被同檔呼叫數百次的巨集 `CTL` 回報內部錯誤,單一符號讓上萬次查詢的
整個 build 陣亡。已修:單一符號的 cscope 查詢失敗改為 warn+跳過,不中止整個
build(`docs/design.md` §8.5.4 D15,已 commit `2cfc7b9`)。這正是 harness 真機
測試的價值——問題在跑真 benchmark 之前就被抓到,而不是在使用者的 repo 上才爆炸。

## 結果總表

| 題 | A 分數 | B 分數 | A cost/turns/time | B cost/turns/time |
|---|---|---|---|---|
| WRQ-008(redis, entry-path,SET 呼叫鏈) | 3 | 3 | $0.55 / 18 turns / 149s | $0.48 / 9 turns / 104s |
| WRQ-009(wpa, callback-indirect,96 欄位) | 3(摘要算術有誤) | 3 | $0.23 / 3 turns / 43s | $0.52 / 8 turns / 105s |
| WRQ-013(wpa, kconfig-build,CONFIG_SAE) | 3†(原評 2,已再更正) | 3†(原評 2,已再更正) | $1.04 / 19 turns / 309s | $0.81 / 12 turns / 190s |
| WRQ-017(redis, dataflow-lifetime) | 3 | 3 | $0.41 / 10 turns / 65s | $0.55 / 14 turns / 111s |
| **合計** | | | **$2.22** | **$2.36** |

† WRQ-013 分數在 2026-07-07 又被**再一次更正**——這次是我(出題/評分者)自己
的錯,不是兩臂的錯,詳見下方「WRQ-013 逐題詳情」與新增的「第三方工具對照」
章節:第一次 GT 更正(2026-07-06)把 `wpa_supplicant/sme.c` 的 5 個函式算進
「應該找到但兩臂沒找到」,因而把兩臂從 3 分打成 2 分;但題目文字明確寫
「across the whole **src/** tree」,而 `sme.c` 實際路徑是
`wpa_supplicant/sme.c`——跟 `src/` 同層的兄弟目錄,**不在 src/ 樹裡**,不該
算進答案。兩臂原始的 49 個 whole-gated 答案其實完全正確,反而是我當時的
「更正」本身超出了題目範圍。已改回 3 分。

**與第一輪的對比**:第一輪 5 題是 5/5 vs 3/5(正確性懸殊);這輪 4 題兩臂
**分數幾乎打平**(3-3-3-3 vs 3-3-3-3,WRQ-013 更正後),token/cost 也打平
($2.22 vs $2.36,B 略高 6%)。這是重要的誠實負面結果,下面逐題說明為什麼,
以及真正的差異出在哪。

## 逐題詳情

### WRQ-008 — redis SET 呼叫鏈(L3,entry-path)

兩臂都**完整且正確**追出 `processCommand → lookupCommand/call → setCommand →
setGenericCommand → setKeyByLink → (exists?dbSetValue:dbAddByLink) →
kvstoreDictSetAtLink`,而且都追到了比我原始 GT 更深一層(`kvstore.c`/`dict.c`
的分片字典寫入)——**我的手工 GT 這題也不夠深**,已對照真源碼驗證兩臂的宣稱
全部屬實(非幻覺)。

差異:B 主動標注了一跳無法在圖中直接呈現的地方(`c->cmd->proc(c)` 是 fn-pointer
dispatch,ccodegraph 的邊語意抓不到這種「透過 struct 欄位呼叫」,而不是透過
`.field=fn` 註冊表——這是我們 fnptr 啟發式目前抓不到的一類間接呼叫),並主動用
grep + `commands.def` 交叉驗證這個環節。這正是 SKILL 風險章教的行為
(「answer-critical 時才驗證」)。A 沒有明講這個侷限,但答案本身依然正確。
B 用一半的 turns(9 vs 18)、更快(104s vs 149s)、更便宜。

### WRQ-009 — wpa driver_ops 96 欄位(L3,callback-indirect)

**這題最出乎意料**:題目設計的假設是「grep 臂會在 136 欄位的巨大 struct literal
中途放棄」——**沒有發生**。逐欄核對後,A 的 96 個 field→function 配對**跟 B 一樣
100% 正確、零遺漏、零錯誤**(A 用一次 Read 把整個 92 行的 struct literal讀完,
3 個 turn 就答完)。

差異只在**最後的摘要算術**:真實情況是 98 個 `.field=` 賦值(96 個函式指標 +
`.name`/`.desc` 2 個字串),其中 11 個(`CONFIG_TDLS`×4、`ANDROID_P2P`×3、
`ANDROID`×1、`CONFIG_MESH`×3)在 `#ifdef` 內。**B 的總數完全正確**
(96 函式 + 2 字串 = 98,並主動做了「機械式計數」交叉驗證,還額外抓到兩個
欄位名與函式名不同的案例、一個跨行欄位);**A 把 2 個字串欄位誤算進函式指標
總數,條件編譯欄位數也多算 1 個**,導致總結說「99 個函式指標」而非正確的 96
——但這只是**收尾時的加總錯誤,不是遺漏或幻覺**,底層列表是對的。

判讀:這題沒有驗證到我原本預期的「規模差異化」假設,是誠實的負面結果;
但驗證出另一個真差異——B 對「總數宣稱」的精確度更高,而這正是使用者會拿著
答案去做決策時最容易被忽略、卻最致命的一種錯(數字聽起來很有道理,實際上算錯了)。

### WRQ-013 — wpa CONFIG_SAE 函式層級歸戶(L4,kconfig-build)

**我的原始 GT 本身不完整**,這是本輪最重要的方法論發現:我只用文字 grep 找
`#ifdef CONFIG_SAE` 出現處,沒檢查 Makefile 層級的整檔條件編譯——
`wpa_supplicant/Makefile:241-243` 有 `ifdef CONFIG_SAE … OBJS += ../src/common/
sae.o … endif`,代表 `src/common/sae.c` 全部 **35 個函式**都只在 CONFIG_SAE
下才會被編進執行檔,這比我原始 GT 認定的 19 個 whole-gated 函式多了一整個檔案
的量。**兩臂都獨立發現了這個 Makefile 機制**(讀了 Makefile,不只是掃原始碼),
各自答出 49 個 whole-gated(35 sae.c + 14 ieee802_11.c)——比我的原始 GT
(19 個)更完整、更正確。

**這裡我在 2026-07-06 做了一次「更正」,結果是我自己的錯**:我當時另外把
`wpa_supplicant/sme.c` 的 5 個函式(`index_within_array`、`sme_set_sae_group`、
`sme_auth_build_sae_commit`、`sme_auth_build_sae_confirm`、`sme_sae_auth`)
也算進「應找到的答案」,湊出 35+14+5=**54**,並因此把兩臂從 3 分打成 2 分
(「漏掉 sme.c」)。**這個更正本身是錯的**——2026-07-07 補做 CodeGraph/cbm
第三方對照時(見下方新章節),兩個工具都獨立答出 35+14=**49** whole + 9
partial = 58,其中 **cbm 的答案明確指出**:`wpa_supplicant/sme.c`、
`mesh_rsn.c`、`config.c` 都在 `src/` 樹**之外**,依照題目原文「across the
whole **src/** tree」的字面範圍,不應該算進去。我重新確認路徑:`sme.c` 在
`wpa_supplicant/sme.c`,跟 `src/` 是repo根目錄下的兄弟目錄,**不在 src/ 裡**
——題目問的就是 `src/` 樹,`sme.c` 本來就不該算。也就是說,兩臂在原始跑的
時候答的 **49 whole + 9 partial = 58**,其實從頭到尾就是對的;錯的是我後來
「更正」時沒有重讀題目本身的範圍限定詞。**已改回 3 分**,`questions.jsonl`
的 GT 也已經第二次更正(保留兩輪更正紀錄供未來對照)。

判讀:這題最大的收穫,不是 A vs B 的差異(兩臂原始表現完全打平且都正確),
而是**「評分者更正 GT 時,一樣要用同一套「不要看一半就下結論」的紀律」**
——我在做第一次更正時,只顧著找「兩臂還有沒有漏掉別的檔案」,卻沒有回頭
檢查題目自己寫的範圍限定詞(「src/ tree」),犯的正是 taxonomy.md 警告
agent 不要犯的同一種錯(只是這次錯的人是我,不是 agent)。

### WRQ-017 — redis createStringObject 生命週期(L4,dataflow-lifetime)

兩臂都與我(已對照真源碼逐行驗證過的)GT **完全一致**:6 個本函式內配對釋放
(`setGenericCommand`/`getexCommand`/`msetexCommand`/`increxCommand` 的
`milliseconds_obj`,以及 `lcsCommand` 的 `obja`/`objb`),4 個所有權轉移給
資料庫、無本地釋放(`incrDecrCommand`/`incrbyfloatCommand`/`increxCommand`
兩處的 `new` 物件)。兩臂都**額外主動指出**我的 GT 沒特別強調的一個細節:
`incrDecrCommand`/`incrbyfloatCommand` 有個「原地重用既有物件」的快速路徑
(`refcount==1` 且已是 int encoding 時直接改值,根本不進入 `createStringObject*`,
既無配置也無需釋放)——這比我的 GT 更細緻,兩臂獨立發現,分數同為 3。

## 誠實結論

1. **這批「更難」的題目,在正確性維度上兩臂幾乎打平**——第一輪 5/5 vs 3/5
   的懸殊差距**沒有重現**。原因不是題目不夠難(WRQ-013/017 是貨真價實的 L4),
   是**當給予足夠的 turns/預算時,一個有紀律的 grep 臂也能把多跳鏈追完、
   把大型 struct literal 讀完**——這點推翻了我在 taxonomy.md 裡「grep 臂會
   在大 struct literal 中途放棄」的預設,必須誠實記下。
2. **真正的差異轉移到:精確度細節(WRQ-009 的加總算術)、風險自覺行為
   (WRQ-008 的 fnptr 侷限主動標注)、效率(3/4 題 B 用更少 turns/更快,
   僅 WRQ-009 反過來)**——這比「答對 vs 答錯」更細膩,也更貼近真實產品
   價值主張:**不是唯一能答對的路,是更快、更便宜、更懂得標注自己不確定
   的地方**的那條路。
3. **GT 本身的建構品質是這次最大的方法論收穫,而且這個問題不只發生在「第一次
   建 GT」,也發生在「事後更正 GT」本身**:WRQ-008 兩臂追得比我原始 GT 更深;
   WRQ-013 更戲劇化——我在 2026-07-06 「更正」GT 時,自己犯了跟 taxonomy.md
   警告 agent 不要犯的同一種錯(沒有把題目的範圍限定詞「src/ tree」讀完整,
   誤把 src/ 樹外的 `sme.c` 也算進「應該找到」的答案),結果把兩臂原本正確的
   3 分錯改成 2 分——直到 2026-07-07 補做 CodeGraph/cbm 對照時,cbm 主動指出
   `sme.c` 在 src/ 樹外,才發現這個更正本身是錯的(已改回 3 分,見下方「第三方
   工具對照」與 WRQ-013 更新後的逐題詳情)。未來這類硬題榜,GT 建構**與事後
   更正**都應該視為與題目本身同等重要的產出,且需要同樣的「不要讀一半就放棄、
   不要忘記題目自己寫的範圍限定詞」紀律。
4. Token/cost 兩臂打平($2.22 vs $2.36),不像先前那樣有系統性方向——這批
   N=1 的變異數也可能較大(WRQ-009 就是一個 turns 3 vs 8 的極端例子),
   正式結論需要 N=3+ 才能收斂,已列入限制。

## Arm B 到底有沒有真的用「圖」的能力?(從 8 份真實 transcript 挖出的證據)

使用者的猜測:「使用 ccodegraph 是不是被當作 grep/find 在用,而不是真的發揮
圖的技巧,要不然結果都會一樣?」——這值得用證據回答,不是猜測。我把 8 次
headless 執行(4 題 × 2 臂)的完整 session transcript(`~/.claude/projects/*/`
下的 `.jsonl`)全部取出,逐一列出每次執行實際下的每一條 Bash 指令,結果如下:

| 題號 | A 臂指令數/技巧 | B 臂指令數/技巧 | 圖能力有沒有被用上? |
|---|---|---|---|
| WRQ-008 | 17 次,純 grep 逐檔追蹤呼叫鏈 | **6 次**,含一條 SQL `JOIN` 查詢直接把呼叫鏈關聯查出來,另外用少量 grep 覆核 fnptr dispatch | **有**——B 用圖把多跳呼叫鏈一次查出來,指令數不到 A 的一半 |
| WRQ-009 | 2 次,一次 `Read` 把整段 92 行 struct literal 讀完,一次 awk 覆核 | 4 次,**核心技巧跟 A 完全一樣**(讀 struct literal 逐欄核對),只多用了一次 schema 查詢做開場定位,實質上退化成同一招 | **沒有**——這題的知識(struct literal 欄位列舉)不是 ccodegraph 有建模的邊類型,B 只能跟 A 一樣用讀檔 |
| WRQ-013 | 18 次,大量 grep `#ifdef`/`endif` 配對、讀 Makefile | 9 次,一條 SQL `COUNT` 查詢交叉驗證總數,但**主要工作仍是大量 grep**(條件編譯的巢狀結構圖裡沒有邊可查) | **部分**——SQL 只用來做總數覆核,實際定位條件編譯區塊仍退回 grep,因為這類知識目前沒有圖邊可用 |
| WRQ-017 | 5 次,grep 找配置點 + 讀函式本體 | **4 次**,一條 SQL `JOIN` 直接查出配置點所在函式與其後續呼叫關係,只補一次 grep 做細節覆核 | **有**——資料流生命週期在圖裡有明確的呼叫關係邊可查,B 明顯用上了 |

**結論:使用者的猜測是對的,但有清楚的邊界**——當題目問的知識**是圖裡已經
建模的邊類型**(呼叫關係、資料流路徑)時,B 臂會真的用 SQL/圖查詢一次查出
答案,指令數顯著少於純 grep 的 A 臂(WRQ-008、WRQ-017);但當題目問的知識
**圖裡沒有建模**(struct literal 逐欄枚舉、條件編譯的函式層級歸戶)時,
B 臂沒有邊可查,只能跟 A 臂一樣退化成讀檔/grep——這正是 WRQ-009 兩臂
「完全同招」、WRQ-013 兩臂「共享同一個盲點」的根本原因。**差異不是
「ccodegraph 有沒有用」,是「這題的知識有沒有被 ccodegraph 建模」**。
這個結論本身也直接指向下一節的改進方向。

## Arm C:redis 真實 compile_commands.json 三方對照(2026-07-07 補做)

使用者提出第三個問題:「有沒有跟正確的 `compile_commands.json` 比較過?」
——上面 Arm B 用的其實是 ccodegraph 在**沒有真實建置產物**時的合成
compile DB(confidence 0.93,無真實 `-D`/`-I`,單一組態盲點)。redis 這邊
剛好留有一份先前用 `bear` 真實建置產生的 `compile_commands.json`
(357 entries,含正確的 `-D`/`-I`/`-std` 等旗標),於是新增 **Arm C**:
其餘條件與 Arm B 完全相同(乾淨複本、專案層 skill、預先 build),唯一差異是
把這份真實 DB 放進複本根目錄再跑 `build`+`clink-import`——`status`/
`clink-import` 的偵測邏輯(`ccodegraph.py:1290-1296`)會自動採用
`root/compile_commands.json`,confidence 提升到 0.95。範圍依使用者指定
(「先只做 redis 的 2 題」):只跑 WRQ-008、WRQ-017,wpa 沒有真實建置產物
(需要 openssl-dev/libnl-dev 等依賴),故不在此列,列為未來工作。

| 題 | A(無 ccodegraph) | B(ccodegraph + 合成 DB,0.93) | C(ccodegraph + 真實 DB,0.95) |
|---|---|---|---|
| WRQ-008 | 3 分 / $0.55 / 18 turns / 149s / 17 次 bash | 3 分 / $0.48 / 9 turns / 104s / 6 次 bash | 3 分 / $0.48 / 10 turns / 91s / **7 次 bash**(含 1 條 SQL) |
| WRQ-017 | 3 分 / $0.41 / 10 turns / 65s / 5 次 bash | 3 分 / $0.55 / 14 turns / 111s / 4 次 bash(含 1 條 SQL JOIN) | 3 分 / $0.61 / 15 turns / 122s / **4 次 bash**(含 1 條 SQL JOIN) |

**逐項核對後,C 臂兩題答案與 B 臂實質相同**:WRQ-008 一樣完整追出
`processCommand → lookupCommand → call → c->cmd->proc(c)(commands.def
fnptr dispatch) → setCommand → setGenericCommand → setKeyByLink →
dbAddByLink/dbSetValue → dbAddInternal → kvstoreDictSetAtLink`,每一跳都
標注 `[cscope,clink; semantic:confirmed]`;WRQ-017 一樣答出 6 個本函式內
釋放 + 4 個所有權轉移給資料庫,連分類、變數名稱、行號都與 B 臂逐項吻合。
兩題所用的 ccodegraph 指令招式也高度相似(WRQ-008 都用
`explore`/`callers`/`sql` 組合;WRQ-017 都以一條 SQL `JOIN` 查詢為主,
輔以少量 grep 覆核),差異只在呼叫次數 ±1、cost/turns/time 在個位數
百分比內浮動(且已知 N=1 本身變異數不小,見前面「N=3」說明,不能只憑
這兩題的數字就說 C 比 B 慢或快)。

**誠實結論:對這 2 題而言,真實 compile_commands.json 沒有帶來可觀察到的
正確性或技巧差異**——合成 DB 雖然沒有真實 `-D`/`-I`,但 clink 對這兩題
牽涉到的檔案(`server.c`/`t_string.c`/`db.c`)解析出的呼叫關係已經與
cscope 一致(`semantic:confirmed`),兩者本來就沒有分歧可讓真實 DB 去仲裁。
**這不代表真實 compile DB 普遍沒有價值**——它的價值在使用者原本就點出的
「單一組態盲點」:當程式碼有大量 `#ifdef CONFIG_*`/巨集依賴不同 `-D` 而
編譯出不同內容時(例如 wpa_supplicant 的 CONFIG_SAE 之類條件編譯,或
redis 自己的 `USE_JEMALLOC` 等旗標),合成 DB 只能猜一組固定的巨集展開,
可能與 grep/clink 對其他組態下的程式碼產生分歧;而這兩題剛好都落在
**沒有巨集/組態分支的直線呼叫鏈或資料流路徑上**,不是這種盲點會發作的
題型。換句話說:這次驗證確認了「合成 DB 對呼叫鏈類題目已經夠用」,但
**沒有**驗證到「合成 DB 在條件編譯密集的程式碼上是否會出錯」——那才是
真實 DB 真正該發揮的場景,而 wpa 的真實建置(WRQ-013 那類題目)正是這種
場景,可惜目前還沒有真實建置產物可供對照,留待未來取得 wpa 真實
`compile_commands.json` 後再做這組對照,才能真正驗證使用者的假設。

## 第三方工具對照:CodeGraph、cbm(2026-07-07 補做,Opus 4.8)

使用者接著問:「CodeGraph 是不是有提供不同的東西?我們要不要實測一下,才知道
現在的上限在哪?」——於是用同一組 4 題(WRQ-008/009/013/017)、同樣的隔離
手法(`git archive HEAD` 乾淨複本 + `--setting-sources project`),新增兩個
**第三方工具**當對照組:

- **CodeGraph**(colbymchenry/codegraph,tree-sitter,`codegraph init` 預建
  索引,agent 用 `callers`/`callees`/`impact`/`explore`/`node`/`query` 等
  CLI 子指令,必要時查 `.codegraph/codegraph.db`)。
- **cbm**(win4r/codebase-memory-mcp-pro fork,tree-sitter,`cli
  index_repository` 預建索引,agent 用 `cli query_graph`〔openCypher〕/
  `cli trace_path` 回答)。兩者都是這個專案更早期(2026-06 底)研究
  `~/git/cbm-vs-codegraph-bench/` 時就已經裝好、驗證過會動的工具,那次研究
  也是這次 ccodegraph 專案本身的緣起之一。

兩個工具都透過 CLI(Bash 工具)呼叫,不是掛 MCP——跟 ccodegraph 的 Arm B/C
測試方式對稱(同樣是 Bash 呼叫 `./ccodegraph.py`),不是因為這兩個工具做不到
MCP(它們事實上都支援,見 `~/git/cbm-vs-codegraph-bench/ARCHITECTURE.md`)。
harness:`tools/run_hard_ab_thirdparty.py`。

**模型一致性**:第一次跑這組對照時我原本打算改用 `--model claude-sonnet-5`,
但檢查先前 10 次 ccodegraph A/B/C 執行的 `modelUsage` 欄位後發現**那 10 次
其實跑的是 Opus 4.8**(headless CLI 沒帶 `--model` 時吃的預設值),所以最後
改為讓 CodeGraph/cbm 這 8 次也統一用 `--model claude-opus-4-8`,才能讓
cost/turns 這類數字跟 ccodegraph 的既有結果直接比較(而不是被模型差異混淆)。

### 結果總表(4 工具 × 4 題)

| 題 | ccodegraph A(grep) | ccodegraph B(合成DB) | CodeGraph | cbm |
|---|---|---|---|---|
| WRQ-008 | 3 / $0.55 / 18t / 149s | 3 / $0.48 / 9t / 104s | 3 / $0.51 / 18t / 87s | 3 / $0.69 / 17t / 155s |
| WRQ-009 | 3(算術誤)/ $0.23 / 3t / 43s | 3 / $0.52 / 8t / 105s | 3(同款算術誤)/ $0.24 / 4t / 44s | 3 / $0.33 / 3t / 73s |
| WRQ-013 | 3†/ $1.04 / 19t / 309s | 3†/ $0.81 / 12t / 190s | 3 / $0.78 / 11t / 176s | 3 / $0.84 / 12t / 251s |
| WRQ-017 | 3 / $0.41 / 10t / 65s | 3 / $0.55 / 14t / 111s | 3 / $0.54 / 15t / 108s | 3 / $0.44 / 10t / 123s |

† 見上方「結果總表」註解與 WRQ-013 逐題詳情的更正說明。**四個工具在全部 4 題
上都拿到滿分**——這是這輪最直接的觀察:當模型固定用 Opus 4.8、給足 turns/
budget 時,三個知識圖工具(ccodegraph、CodeGraph、cbm)與純 grep 基準線
在這 4 題的**最終正確性上完全沒有差異**。真正的差異藏在「怎麼答對的」。

### 逐題:怎麼答對的,差在哪

**WRQ-008(redis SET 呼叫鏈)**——這題最能體現 cbm 的已知硬傷:cbm 自己在
答案裡誠實寫出「`trace_path` 回傳空的 callees,節點也沒有 file/line 屬性
——這個 C 索引的 CALLS 邊是檔案級,不是函式級」,於是整題**16 次 bash 呼叫
幾乎全是 grep/awk/sed**,實質上退化成跟 grep 基準線一樣的技巧(這也印證了
更早期 `~/git/cbm-vs-codegraph-bench/REPORT.md` 就已經記錄的發現:cbm 的
CALLS 邊在 C 專案上 ~99% 掛在檔案節點而非函式節點)。CodeGraph 則反過來
**用了 12 次自己的 `codegraph node <fn>` 查詢**逐跳確認每個函式的呼叫者/
被呼叫者,但沒有用效率更高的 `callers`/`impact`,最終仍需要 2 次 grep 補
`c->cmd->proc(c)` 這個函式指標分派跳——總計 17 次 bash 呼叫,跟純 grep 的
ccodegraph Arm A(17 次)幾乎打平,沒有展現出圖查詢應有的效率優勢。

**WRQ-009(struct literal 136 欄位列舉)**——**兩個第三方工具都只用了
1 次 grep 定位 + 1 次 Read 把整段 struct literal 讀完**(CodeGraph 3 次
bash + 1 次 Read;cbm 1 次 bash + 1 次 Read),完全沒有呼叫任何一方的圖
查詢能力(CodeGraph 的 `query`/`node`、cbm 的 Cypher 都沒被用上)。這跟
ccodegraph 的 Arm A/B 在這題「兩臂技巧完全相同」的模式一致——**現在有
三個獨立工具、兩個模型都印證同一件事:struct literal 逐欄枚舉這種知識,
沒有一個圖工具把它當成一等公民建模,遇到這類題目一律退化成讀檔**。

**WRQ-013(CONFIG_SAE 函式歸戶)——這裡意外挖出一個評分者自己的錯**:
CodeGraph 和 cbm 都獨立答出 **35(sae.c)+ 14(ieee802_11.c)= 49 whole +
9 partial = 58 總計**,兩者都完全沒有把 `wpa_supplicant/sme.c` 算進去。
起初我以為這是兩個新工具「跟 ccodegraph 原本兩臂共享同一個盲點」,但
**cbm 的答案裡明講了理由**:「SAE functions in wpa_supplicant/sme.c,
mesh_rsn.c, config.c ... are outside `src/` and excluded per the task」
——回頭核對路徑,`sme.c` 確實是 `wpa_supplicant/sme.c`,跟 `src/` 是
repo 根目錄下的**兄弟目錄**,不在 `src/` 樹裡,而題目原文明寫「across
the whole **src/** tree」。也就是說:**這不是四個工具/兩個模型的共同
盲點,是我在 2026-07-06 更正 GT 時自己漏看了題目的範圍限定詞**,把
`sme.c` 錯誤地算進「應找到的答案」,因而錯把兩臂原本正確的 49/58 打成
「漏答」而扣分。已在上方「結果總表」與 WRQ-013 詳情更正(改回 3 分),
`questions.jsonl` 的 GT 也已第二次更正。CodeGraph 和 cbm 在方法上都沒有
用自己的圖查詢做這題——兩者都是 grep `#ifdef CONFIG_SAE` 全文出現處 +
交叉核對 Makefile + 手動找外圍函式邊界(CodeGraph 10 次、cbm 11 次 bash,
全是文字工具),再次確認**條件編譯的函式層級歸戶,在 ccodegraph、
CodeGraph、cbm 三個工具上都沒有被建模成圖邊**,一律退化成 grep。

**WRQ-017(createStringObject 生命週期)——這題是本輪唯一一個 ccodegraph
展現出圖查詢優勢、而兩個第三方工具都沒有的案例**:ccodegraph 的 Arm B/C
都用一條 SQL `JOIN` 查詢直接把「配置點所在函式」與「後續呼叫」關聯查出來
(4 次 bash);但 CodeGraph(9 次 bash + 5 次 Read)與 cbm(3 次 bash +
6 次 Read)**都沒有呼叫任何圖/查詢能力**,一律用 grep 定位配置點、
Read 讀函式本體判斷歸屬。cbm 明明有跟 ccodegraph 一樣通用的 Cypher
查詢能力,卻在這題完全沒被用上——可能的原因是 ccodegraph 的 `sql` 逃生口
與 CodeGraph/cbm 暴露給 agent 的固定子指令集(`callers`/`callees`/
`impact`/`query_graph`)相比,更容易讓 agent 臨時湊出一條「這個函式呼叫的
下一步是誰」這種一次性關聯查詢,而不需要學一套查詢語言的語法(SQL 本身
在訓練資料裡出現頻率遠高於這兩個工具各自的 Cypher/CLI 語法)——這是本輪
唯一支持「ccodegraph 的 raw SQL 逃生口本身是差異化優勢」的證據,值得記錄
但樣本數(1 題)太小,不能斷言。

### 一個跨工具、跨模型都重複出現的錯誤模式:總數算術

WRQ-009 這題,ccodegraph 原始 Arm A(grep,無工具)算出「99 個函式指標」,
這次 CodeGraph(有自己的圖工具、Opus 4.8)**答出一模一樣錯誤的「99」**
——底層列出的 96 個函式指標欄位本身完全正確,但收尾加總時「86 unconditional
+ 11 conditional」被寫成「99 總計」(正確應是 86+11=97,而且 86 本身也
數錯了,table 實際列了 85 行)。同一輪,CodeGraph 在 WRQ-013 也犯了同類
錯誤:條列了 8 個 `.c` 檔案,卻在總結寫「分布於 6 個 .c 檔」。**三次獨立
發生**(ccodegraph Arm A、CodeGraph WRQ-009、CodeGraph WRQ-013),都是
「底層列表正確,收尾口頭加總卻算錯」——這不是某個工具特有的毛病,更像是
Opus 4.8(或大型語言模型整體)在列出大量條目後手動加總時的通性弱點,
強化了下方「改進方向」第 4 點(教 agent 用獨立 COUNT 查詢覆核總數)不只
對 ccodegraph 有意義,是所有工具都該教的通用紀律。

### 一個隔離漏洞(誠實記錄,不影響這題答案內容)

cbm 跑 WRQ-009 時,第一條 bash 指令沒有用乾淨複本的路徑,而是用一個相對
`CBM_BIN`(prompt 裡給的 cbm 二進位絕對路徑)算出來的路徑
`.../cbm-fork/../`,意外落到 `~/git/cbm-vs-codegraph-bench/repos/`
(這個 benchmark 專案本身存放原始 repo 的地方),grep 命中的是**沒有經過
`git archive` 隔離的原始 wpa_supplicant checkout**,不是這次 harness
準備的乾淨複本。事後核對:`git status`/`git diff` 確認該次讀到的
`src/drivers/driver_nl80211.c` 在原始 checkout 裡**沒有任何未提交修改**,
所以答案內容本身沒有受影響;但這是 harness 隔離手法的一個真實漏洞——
prompt 裡給第三方工具二進位的絕對路徑,可能讓 agent 用它反推出其他目錄
再跳出乾淨複本。未來這類 harness 若要更嚴謹,應該考慮把工具二進位也軟連結
進複本內部,或跑完後自動檢查每個工具呼叫的路徑是否都落在複本目錄下。

## 改進方向(從這次證據歸納,刻意不寫進 ccodegraph 程式碼)

以下是根據上面的證據整理出的、**可能有價值的一般化改進方向**,故意只留在
文件層級討論,不在這次直接動 `ccodegraph.py`——一來還沒有第二個獨立案例
驗證是否過度針對這 4 題(overfitting),二來這類設計決策動輒影響 schema,
應該獨立立案評估,不該因為一次 benchmark 就倉促動手:

1. **struct literal 的欄位列舉目前沒有被建模成圖邊**——WRQ-009 顯示,當
   知識形式是「某個 struct literal 裡有哪些 `.field = fn` 賦值」時,ccodegraph
   現有的 fnptr 啟發式(`.field=fn` 註冊表)不足以涵蓋,B 臂只能跟 A 臂一樣
   讀檔逐欄核對。**這不是 ccodegraph 特有的缺口**——2026-07-07 補做的
   CodeGraph、cbm 第三方對照裡,兩者也完全沒用上自己的圖查詢能力,同樣是
   1 次 grep 定位 + 1 次 Read 整段讀完(見「第三方工具對照」章節),三個
   獨立工具、兩個模型都印證同一個結論。如果要延伸,方向會是:把「某個具名
   struct literal 內所有 `.field = expr` 賦值」當作一種獨立的可查詢邊
   (不只是函式指標,字串/數字欄位也一併記錄),但這牽涉 schema 擴充與
   clang AST 解析成本,需要獨立評估。
2. **條件編譯(`#ifdef`)目前只有檔案層級的粗粒度資訊,沒有函式層級的區塊
   邊界**——WRQ-013 顯示兩臂都要靠大量 grep 才能自己去配對 `#ifdef`/`#endif`
   與函式邊界。**這同樣不是 ccodegraph 特有的缺口**:CodeGraph、cbm 對這題
   一樣完全沒用圖查詢,全靠 grep `CONFIG_SAE` 全文出現處 + 手寫 awk 找外圍
   函式邊界。(先前這裡曾寫「兩臂都漏掉 sme.c」,但那是我在更正 GT 時自己看
   漏題目的範圍限定詞——`sme.c` 根本不在題目要求的 `src/` 樹裡,不是真的
   遺漏,已更正,見上方「第三方工具對照」章節與 WRQ-013 逐題詳情。)如果
   ccodegraph 能把「這個函式的哪幾行落在哪個 `#ifdef` 條件裡」記成邊
   (關聯到現有已保留但未填的 kconfig-build 層),應該能真正把這類題目從
   「退化成 grep」提升為「圖查詢」。
3. **Makefile 層級的整檔條件編譯(`OBJS += ... ifdef ... endif`)是跟原始碼
   內 `#ifdef` 完全不同的一種閘控機制**,這次連我人工建 GT 都一開始漏算
   (WRQ-013 的更正記錄)。如果圖裡能額外標記「這個檔案整個只在某個 build
   flag 下才會被編譯」(來源可以是解析 Makefile,不需要語意分析),對這類
   題目會是低成本、高回報的一塊。
4. **「用另一條獨立的 COUNT/彙總查詢覆核自己的總數宣稱」值得當作明確教給
   agent 的一般性技巧,而不只是它自己偶然做對**——WRQ-009 裡 B 主動做了
   機械式計數覆核、WRQ-013 裡 B 也用 SQL COUNT 覆核總數,兩次都抓到或避開了
   加總錯誤;A 兩次都在最後手動加總時出錯。**2026-07-07 的第三方對照又
   獨立重現了同一種錯**:CodeGraph 在 WRQ-009 答出跟 ccodegraph 原始 Arm A
   一模一樣的錯誤總數「99」,在 WRQ-013 也把「列了 8 個檔案」誤總結成
   「6 個檔案」——三次獨立發生,兩個不同工具,同一個模型(Opus 4.8),
   這比原本只看到一次更有力地說明:**這是模型在列出大量條目後手動加總的
   通性弱點,不是特定工具的偶然缺陷**,值得當作對所有工具都通用的教學
   紀律。可以考慮在 SKILL.md 的風險/驗證章節裡,更明確地把「宣稱總數前,
   用一次獨立查詢複核」列為一般性步驟(不限於某一類問題),但這是文件層級
   的教學調整,不涉及程式碼變更,留待下次修 SKILL.md 時一併考慮。

## 限制

- N=1 先導,同第一輪;WRQ-009 的 turns 落差(3 vs 8)提示變異數可能不小,
  正式版本需要 N=3。
- 4 題皆由我人工對照源碼評分,沒有第三方獨立複核;為避免自我驗證偏誤,
  未來可考慮找 codex 或另一個 session 做盲評(不告知哪個是哪個工具)。
- WRQ-013 的 GT 經過兩輪更正(19→54→58),第二輪更正把 `sme.c` 排除是因為
  它在題目字面範圍(「src/ tree」)之外,而不是因為找到了新的 CONFIG_SAE
  機制;**58(49 whole + 9 partial)在 src/ 樹內本身也未必是「終局真相」**
  ——不排除 `src/` 樹內還有第三種我依然沒發現的 CONFIG_SAE 閘控機制(例如
  header 裡更隱蔽的巢狀巨集)。這正是這套 benchmark 想揭露的問題本質:
  C 語言條件編譯的完整性驗證極難窮盡,連反覆核對的人類(這次還連續核對
  兩輪)都可能在範圍界定或深度上出錯——這次甚至是**評分者的錯誤,不是
  被評分的 agent 的錯誤**,值得作為這整套方法論最誠實的一條限制記下來。
- Arm C(真實 compile_commands.json)**只做了 redis 的 2 題**,且剛好是
  兩題都不涉及條件編譯/巨集展開的直線呼叫鏈與資料流路徑——這是使用者
  明確選定的範圍(「先只做 redis 的 2 題」),不是能力不足。wpa 的真實
  `compile_commands.json`(需要先裝 openssl-dev/libnl-dev 等依賴跑一次真實
  build)以及最可能讓「合成 vs 真實 DB」出現分歧的 WRQ-013 這類條件編譯題,
  都還沒有用真實 DB 對照過,留作未來工作(harness:`tools/run_hard_ab_armc.py`,
  目前只掃 `CASES` 裡的 2 個 redis 題,要加 wpa 只需在有真實 build 產物後
  補上對應 case)。
