# ccodegraph — 需求(Why & What)

> How(schema、演算法、歸戶規則)在 [design.md](design.md)。
> 本文件回答「為什麼做、做什麼」——團隊交接時先讀這份。

## 1. Why — 使命與哲學(每條取捨都有原因,交接必讀)

**W1. Token 經濟是第一因。** LLM 用 grep+Read 探索 C 程式碼,每個問題要幾十次往返、
燒掉大量 token,而且會**靜默答錯**(fn-pointer 分派類問題,實測無工具時完成度 0%)。
解法不是讓 LLM 更努力,是**把重複的機械工作交給固定程式,LLM 只做高階判斷**——
選用哪個工具、要哪些資料、怎麼解讀含糊訊號。

**W2. 分層資訊策略:圖譜先答,grep 是最後手段。** 工具提供基本 AST 級資訊
(節點、行區間、呼叫/讀寫/包含關係);LLM 需要進階細節時,拿著圖給的精確
`file:line` 再去讀原始碼——不是反過來先 grep 再猜。這個順序就是 token 節省的來源。

**W3. C 優先(80% 工時),C++ 輕量(20%)。** 我們的真實工作負載是 C(韌體、驅動、
系統層);C++ 的可證偽定義是:**保留 parser 可觀測到的符號與近似關係**(檔案照收、
符號進節點、直接呼叫進邊、全部標 origin)。明確非目標:template 實例化、overload
解析、虛函式表——這些交給 clangd 層,沒有 clangd 就是近似。輕量、快,
不為 20% 的場景拖慢 80%。(codex R2 審查:原「資訊不漏」無可達成定義,已改。)

**W4. No-build 至上,compile DB 是升級不是門檻。** 80% 場景拿到的是編不起來的
source tree。基礎層(ctags/cscope/tree-sitter)零 build 需求;有
`compile_commands.json`(或可生成)時 clangd 層疊加精度。兩者**整合在同一張圖**,
逐筆標注來源。

**W5. 整合既有 open source 工具,不重寫。** ctags、cscope、tree-sitter、clangd、
clang AST——每個都是數十年打磨的引擎,我們的價值在**組合、歸戶、消歧、標注**,
不在重造解析器。這也讓未來接入**私有工具(如組合語言級 flow 分析)**只是多一個
origin,不是改架構。(實測背書:cscope 直接邊召回 99% 級,自寫 parser 到不了。)

**W6. 誠實是硬需求:confidence + origin 讓 LLM 自行判讀。** 每筆資料標注
「誰說的、多可信」。寧可漏報絕不誤報的落實方式:漏報用多引擎聯集治,
誤報用信心標籤治——不確定的資料**可過濾而不是被刪除**。

**W7. Schema 是合約,先於一切。**「程式碼 → 資料庫」的轉換是另一件工作;
Schema 定義必須自足、完整、不讓大模型困擾——LLM 只看 schema 就該知道
每個欄位的語意與每種值的含義。schema 自省(`schema` 動詞)是第一個查詢動詞。

## 2. 使用者輪廓

| Persona | 需求 |
|---------|------|
| **LLM/agent**(主要) | 一次便宜查詢取代 grep 迴圈;信心標籤判讀;SQL 自助 |
| 開發者(人類) | 快速呼叫圖、全域變數讀寫面、header 影響面 |
| 內網使用者 | 零網路依賴;工具都是系統可裝的老牌 open source |
| 未來:VS Code 使用者 | plugin 讀同一份 graph.db(R5,應用層) |

## 3. What — 功能需求

| ID | 需求 |
|----|------|
| FR1 | **Schema 合約**(design §1):nodes/edges/files/meta + views;邊帶站點 `file:line`、`origin`、`confidence`、`meta` 註記;所有欄位與合法值在 design 文件完整列舉 |
| FR2 | **分層填料**,每層獨立可重跑:L0 ctags 節點 → L1 cscope 邊 → L2 tree-sitter 聯集 → L3 fnptr/callback 啟發式 + **使用者人工表** → L4 clangd 升級 → L5 git 增量;未來開放私有 origin(asm flow 等) |
| FR3 | **fnptr 使用者參數表**(ccq.fnptr.json 血統,必須保留):`registrations`(使用者指定 struct/field → handler)+ `links`(直接連線);manual 邊 confidence 1.0——語意是 **asserted_by_user**(非「證明為真」),記錄來源檔 hash,來源變更時標 stale(codex R2 修正) |
| FR4 | 同名消歧(D1):src 行區間精確歸戶;dst static 同檔規則(header 例外);殘餘 → ambiguous 註記 + 分節呈現 |
| FR5 | 查詢:schema(第一動詞)/callers/callees/impact/globals/vars-of/who-includes/sql(唯讀);預設 confidence ≥ 0.7;ambiguous 邊 callers 顯示、impact 不走(D4) |
| FR6 | **產物集中**:全部在 `<root>/.ccodegraph/`(graph.db、cscope.out、自動 `.gitignore`);未來 user 層狀態放平台 cache dir;**所有路徑可印出,不隱藏**(ccq 經驗) |
| FR7 | git 增量(L5):content_hash + diff 圈重掃集;改 1 檔 <5s、**normalized 圖 diff = 0**(排除時間戳/git_rev 等 volatile 欄,只比 nodes/edges 內容,排序穩定化) |
| FR8 | **查詢層為 LLM 設計**(R4,等 DB 完整後獨立設計):動詞 token 形狀、SKILL.md、「讓大模型知道如何使用」是驗收標準 |
| FR9 | **輸出格式雙軌**:每個查詢動詞支援 `--json`——純文字(人讀/省 token)或 JSON(機器解析),**由 LLM 自行決定要哪種**;JSON schema 與文字欄位一一對應,列入 Schema Contract |

## 4. 非功能需求

| ID | 需求 |
|----|------|
| NFR1 | Python 標準庫 only;外部只依賴既有 binary(ctags/cscope;L2+ tree-sitter/clangd);缺工具明講跳過 |
| NFR2 | **輕量、快**:no-build 基礎層中型 repo(600–800 檔)分鐘級內;C++ 檔案照收不深究 |
| NFR3 | **ctags 跨平台相容**(R2):macOS BSD / Linux Exuberant / Windows 差異——啟動偵測 flavor、參數對映、非 Universal 大聲死 + 安裝指引;CI 三平台 |
| NFR4 | 三層測試(unit/integration/e2e,標準庫 unittest);commit 時全綠;fixture 案例對應每條消歧規則 |
| NFR5 | git 記錄每一次修改;決策(含取捨原因)記入 design.md 決策記錄——**交接資產** |
| NFR6 | 定期第三方紅隊審查(codex)需求與設計文件:盲區、一廂情願、測試不足;報告歸檔 docs/reviews/ |

## 5. 研究項(不承諾時程)

- **R6 Rust 移植**:傳聞 10× 速度;等 Python 版功能完整、schema 穩定後評估——
  schema 是合約,引擎換語言不換合約,所以現在不用為它做任何妥協。
- **R7 clink 研究**(https://github.com/Smattr/clink):cscope 的現代重實作
  (libclang 解析 + SQLite 儲存 + 吃 compile_commands.json)。clone 實跑、
  萃取它對 cscope 的改良;評估當第四個填料 origin(尤其 compile-DB-aware 路線)。

## 6. 驗收(沿用實測 GT)

(需求只寫目標;完成進度見 design.md §9 Roadmap——codex R2:別把進度混進需求)

- **Recall suite**:calls+callback wpa cflow 28/28、redis 73/73;fnptr `.scan2` 5/5;defs ≥99.5%
- **Precision suite**:12 場景誤報防線 pin 成測試;ambiguous/callback 誤報抽查
- **Portability suite**(R2 之後):三平台 ctags flavor;Windows 路徑
- **Failure-mode suite**:工具缺失/壞輸出時的退化行為(見 design 退化矩陣)
- 增量(L5):改 1 檔 <5s,normalized 圖 diff = 0
