# Taxonomy — wpa_supplicant/redis 適配版(仿 linux-kernel-navigation-benchmark)

> 依據 `~/git/knowledge_from_ai_summary/linux-kernel-navigation-benchmark/taxonomy.md` 的 12 類架構,
> 逐類改寫為 wpa_supplicant(C,單執行緒 event loop,大量 `#ifdef CONFIG_*`)與 redis(C,單執行緒
> 事件迴圈 + 少量背景執行緒)適用的版本。**動機**:先前 5 題 A/B 全落在 L1–L2(單點呼叫/單點
> include),grep 臂偶爾矇對,差異不夠戲劇化。這份題庫刻意把重心推到 L3–L4,且每類都寫明
> 「預期哪個引擎會贏、為什麼」,而不是為了出題而出題。

## Difficulty Levels(沿用原定義)

| Level | Meaning | wpa/redis 具體樣貌 |
|---|---|---|
| L1 | 單點查找 | 一個函式定義、一個 macro |
| L2 | 一階關係 | direct caller/callee、直接 include、單一全域讀寫 |
| L3 | 跨檔或間接關係 | callback/ops table、多跳 call path、條件編譯的函式層級歸屬 |
| L4 | 語意推理 | dataflow/生命週期、ownership 轉移判斷 |

## Categories

### 1. `symbol-definition`(適配:直接沿用)
找函式/巨集/struct 定義,分辨 declaration(.h)vs definition(.c)。wpa/redis 都大量把 declaration
放 header、definition 放 .c,對純文字工具是基本題,對 grep 也不難——**留作 L1 對照組**,
不是本輪重點。

### 2. `references-usages`(適配:直接沿用)
找 symbol 使用點,排除 comment/字串常值裡的假 match。wpa/redis 的 log 訊息字串常包含函式名
(如 `wpa_printf(MSG_DEBUG, "eloop: ...")`),是 false-positive 的天然來源。**預期**:grep 臂
會把訊息字串誤當引用;ccodegraph 的 cscope 層本身也是文字比對,同樣可能誤報,但函式級去重
輸出讓誤報比較容易被人眼抓到。

### 3. `caller-callee`(適配:直接沿用,但拉高難度)
先前測過的「誰呼叫 X」是 L2(單函式)。這輪拉到 L3:**跨檔多跳呼叫鏈**(見 entry-path)或
**巨大 ops table 的完整欄位盤點**(見 callback-indirect)——單一函式的直接呼叫已經測過不再重複。

### 4. `entry-path`(適配:kernel 的 syscall entry → redis/wpa 的事件分派入口)
- redis:`processCommand`/`lookupCommand` 分派到 `xxxCommand`,再往下到 `db.c` 層的實際寫入
  (`setKeyByLink`/`dbAddByLink`/`dbSetValue`)——**這是本輪真跑題之一**。
- wpa:`main()` → `wpa_supplicant_run()` → `eloop_run()` → 各種 `eloop_register_*` 回呼——已在
  舊題測過事件迴圈,這輪換 redis 的指令分派鏈,避免重複。
**預期**:多跳鏈需要 agent 自己串起 3–4 個 `callers`/`callees` 查詢或讀多個檔案;
grep 臂通常只能一次看一跳,容易在中間某一跳追丟或漏看間接呼叫。

### 5. `callback-indirect`(適配:直接沿用,大幅拉高規模)
舊題只驗證 `struct wpa_driver_ops` 裡 5 個 `.scan2` handler。這類 ops table 在 wpa 有
**136 個函式指標欄位**,nl80211 driver 實際填了 96 個——**這是本輪真跑題之一**,規模大到
grep 臂必須完整讀完一個巨大 struct literal 才能不漏欄位,而 ccodegraph 的 `callers`
動詞理論上一次列出所有 fnptr 邊(含 origin/confidence 標籤)。

### 6. `data-structure`(適配:直接沿用)
wpa 的 `struct dl_list`(手刻雙向鏈結串列,無 `container_of` 但有等價的 embed-struct 慣例)、
redis 的 `robj`/`kvobj` 型別欄位存取。留作題庫廣度用,本輪不排進真跑 4 題
(container_of 類推理在這兩個 codebase 不如 kernel 普遍,難度不如其他類別鮮明)。

### 7. `kconfig-build`(適配:kernel Kconfig/Makefile → wpa `#ifdef CONFIG_*` / redis `#ifdef USE_*|HAVE_*`)
wpa 有 **1985 處 `#ifdef CONFIG_*`**,這類完全沒測過。**這是本輪真跑題之一**:
給定 `CONFIG_SAE`,要求列出「函式層級」的受控範圍——不是「哪些檔案提到它」(grep 一秒答完),
是要正確處理巢狀 `#ifdef`、區分「整個函式只在此 flag 下存在」vs「函式一直存在但內部一段邏輯
被此 flag 條件化」。**預期**:這題設計來檢驗 ccodegraph 語意層(`semantic:confirmed|absent`)
對條件編譯的誠實標記,以及 grep 對巢狀邊界判斷的已知弱點——純文字 grep 找得到所有
`CONFIG_SAE` 出現行,但要把行號正確歸戶到「整個函式」還是「函式的一部分」,需要結構資訊。

### 8. `include-dependency`(適配:直接沿用)
header 定義與 include graph。ccodegraph 已有 `who-includes`(直接)與 SQL 遞移閉包模板。
留作題庫廣度,不重複排真跑(先前 5 題已測過 include,無新鮮度)。

### 9. `dataflow-lifetime`(適配:直接沿用,聚焦 ownership 轉移而非單純配對)
redis `createStringObject*` 家族配置的物件,追蹤 `decrRefCount` 釋放點——**這是本輪真跑題之一**,
四題中最難。關鍵不是「找到 create 和 decrRefCount 呼叫」(grep 秒答),是要正確分辨
「本函式局部配置局部釋放」vs「配置後所有權轉移給資料庫,釋放發生在別處」——這需要讀函式
語意,不是文字比對。

### 10. `locking-rcu`(適配:kernel lock/RCU → 並發模型;誠實標記不完全適用)
wpa_supplicant 每個行程對單一 interface 是單執行緒 event loop,**沒有 kernel 式的 lock/RCU
語意**,此類對 wpa 不適用,如實記錄而非硬套。redis 有背景執行緒(`bio.c` 的
`pthread_create(&thread,&attr,bioProcessBackgroundJobs,...)`,處理非同步 fsync/free),
適配為「主執行緒與背景執行緒共享狀態的邊界」——列入題庫廣度,難度與前置知識要求高
(需要理解 redis 的 job queue 設計),本輪不排真跑(避免題庫greatest-hit 全部只驗證
「多跳/大規模/語意判斷」這三種能力,故意留一類做未來延伸)。

### 11. `bug-localization`(適配:stack trace/oops → 錯誤訊息字串的建構點)
不是單純 grep 錯誤訊息字串(那是 references-usages 類的簡化版),而是「給一個執行期會看到的
錯誤訊息或回傳碼語意,找到*建構*該訊息或決定該回傳碼的函式與條件」——例如 wpa 的
nl80211 driver 在什麼條件下對 scan trigger 回傳特定錯誤。留作題庫廣度用。

### 12. `version-diff`(適配:明列跳過)
需要 pin 兩個版本做比較,本輪未做(原因與參考資料夾相同)。列為 future work。

## Scoring(沿用 0–3 分制,不變)

| Score | Meaning |
|---|---|
| 0 | 找錯 subsystem、錯 symbol,或答非所問 |
| 1 | 找到部分相關檔案,但核心答案錯或缺少關鍵條件 |
| 2 | 核心答案正確,但漏掉重要呼叫點/欄位/條件,或未區分本題刻意設計的難點(如 whole vs partial gate、ownership 轉移) |
| 3 | 答案完整,且能指出限制、條件與可能的 false positive/覆蓋率缺口 |

## Common Failure Modes(依 wpa/redis 特性補充,非原樣照抄 kernel 版)

- 把 `#ifdef` 出現的**行**當成「函式」層級的答案,沒有做行號→函式的歸戶。
- 巨大 struct literal(136 欄位)只讀了前面幾十行就中斷,漏掉後段欄位。
- 把「配置後交給別的資料結構持有」誤判為「忘了釋放」或反過來忽略未釋放的物件。
- 多跳呼叫鏈只追一跳就停,把中間層(如 redis 的 `setKeyByLink`)誤認為終點。
- 把 log/debug 訊息字串裡的函式名文字誤當成真呼叫。

---

## 附錄:4 個真跑題目的 GT 檔案索引

- WRQ-009(callback-indirect,driver_ops 136 欄位):`gt_case1_driver_ops.txt`
- WRQ-008(entry-path,SET 呼叫鏈):`gt_case2_set_chain.md`
- WRQ-013(kconfig-build,CONFIG_SAE 函式層級):完整名單見 `questions.jsonl` 該題的 evaluation_notes 欄位
- WRQ-017(dataflow-lifetime,createStringObject 生命週期):`gt_case4_lifecycle.md`

所有 GT 皆由本次研究工作階段人工/程式交叉核對真實原始碼推導,非憑空杜撰或引用網路資料。
