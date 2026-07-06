# R4 驗收 v2:硬題 A/B(真 Claude Code headless,N=1,2026-07-06)

> 動機:使用者對第一輪 5 題 A/B(`llm-ab.md`)的反饋——「太簡單,認不出差別」。
> 仿 `linux-kernel-navigation-benchmark` 的分類法為 wpa_supplicant/redis 出了
> 22 題難題庫(`docs/research/hard-benchmark/`,12 類適配、L1–L4),挑 4 題
> 最難的(L3/L4,涵蓋多跳呼叫鏈、136 欄位大型 ops table、條件編譯函式層級歸戶、
> 資料流生命週期)用真 **Claude Code headless mode** 跑,不是 codex。

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
| WRQ-013(wpa, kconfig-build,CONFIG_SAE) | 2(GT 更正後) | 2(GT 更正後) | $1.04 / 19 turns / 309s | $0.81 / 12 turns / 190s |
| WRQ-017(redis, dataflow-lifetime) | 3 | 3 | $0.41 / 10 turns / 65s | $0.55 / 14 turns / 111s |
| **合計** | | | **$2.22** | **$2.36** |

**與第一輪的對比**:第一輪 5 題是 5/5 vs 3/5(正確性懸殊);這輪 4 題兩臂
**分數幾乎打平**(3-3-2-3 vs 3-3-2-3),token/cost 也打平($2.22 vs $2.36,
B 略高 6%)。這是重要的誠實負面結果,下面逐題說明為什麼,以及真正的差異出在哪。

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

但對照更正後的**真實完整答案**(35+14+**5**=**54**,我這次重新逐行核對
`wpa_supplicant/sme.c` 確認那 5 個函式——`index_within_array`、
`sme_set_sae_group`、`sme_auth_build_sae_commit`、`sme_auth_build_sae_confirm`、
`sme_sae_auth`——的函式本體確實整段夾在 `#ifdef CONFIG_SAE`/`#endif` 之間),
**兩臂都漏掉了 `sme.c` 這 5 個 whole-gated 函式**(partial 清單也同樣少了
`sme.c` 裡對應的 partial 函式)。兩臂在這題的表現**完全打平**,共享同一個
盲點:都把主要精力放在 `sae.c`(整檔閘控,容易發現)與 `ieee802_11.c`
(單一大段 `#ifdef`,318–876 行連續),相對輕忽了 `sme.c`(CONFIG_SAE 散落在
8 個不連續的區塊裡,更難逐一收斂)。

判讀:分數 2/2(核心答案正確、機制判斷正確,但相對「真實完整答案」有系統性
遺漏)。這題最大的收穫不是 A vs B 的差異,是**GT 建構本身需要跟我們要求 agent
做到的同一種嚴謹**——我在建 GT 時等於犯了 taxonomy.md 警告的同一種錯
(廣度覆蓋不足,只是我的版本是「三個檔案裡只有兩個查得夠細」而非「大檔案讀到
一半放棄」)。`questions.jsonl` 的 GT 已在此報告更正,供未來重跑對照。

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
3. **GT 本身的建構品質是這次最大的方法論收穫**:WRQ-008/013 兩題我的手工
   GT 都被兩臂的實際表現「撞破」(追得比我深、看得比我廣)。未來這類硬題
   榜,GT 建構應該視為與題目本身同等重要的產出,且需要同樣的「不要讀一半
   就放棄」紀律。
4. Token/cost 兩臂打平($2.22 vs $2.36),不像先前那樣有系統性方向——這批
   N=1 的變異數也可能較大(WRQ-009 就是一個 turns 3 vs 8 的極端例子),
   正式結論需要 N=3+ 才能收斂,已列入限制。

## 限制

- N=1 先導,同第一輪;WRQ-009 的 turns 落差(3 vs 8)提示變異數可能不小,
  正式版本需要 N=3。
- 4 題皆由我人工對照源碼評分,沒有第三方獨立複核;為避免自我驗證偏誤,
  未來可考慮找 codex 或另一個 session 做盲評(不告知哪個是哪個工具)。
- WRQ-013 的更正 GT(54 vs 兩臂的 49)本身也未必是「終局真相」——不排除
  還有第三種 CONFIG_SAE 閘控機制我依然沒發現(例如 header 裡的巢狀巨集)。
  這正是這套 benchmark 想揭露的問題本質:C 語言條件編譯的完整性驗證極難
  窮盡,連反覆核對的人類都可能低估其複雜度。
