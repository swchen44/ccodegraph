# ideal-graph — 需求(Requirements)

## 1. 目的

為 LLM/agent 建立**最完整且誠實**的 C 程式碼知識圖譜:schema 一次到位(格子),
多引擎分層填料(料),每筆資料標注出處(origin)與信心(confidence),讓 LLM 自行判讀。
設計依據與決策紀錄見 [design.md](design.md)。

## 2. 功能需求

| ID | 需求 |
|----|------|
| FR1 | Schema 依 design.md §1:meta/files/nodes/edges 四表 + `edge_pairs`/`file_deps` 視圖;邊帶站點 `file:line`、`origin`、`confidence`、`meta` JSON |
| FR2 | **分層填料**,每層獨立可重跑(只動自己 origin 的列):L0 ctags 節點 → L1 cscope 邊(calls/reads/writes/includes)→ L2 tree-sitter 聯集 → L3 fnptr/callback 啟發式 + manual 表 → L4 clangd 升級(有 compile DB 才跑)→ L5 git(co_changes + 增量) |
| FR3 | 查詢動詞:`schema`(第一動詞:填充率 + 未填層)、`callers`/`callees`(pair 去重 + 首站點 + `(N sites)` + origins 標籤)、`impact -d N`、`globals`(writers/readers 拆列)、`vars-of`、`who-includes`、`sql`(逃生口) |
| FR4 | **同名消歧(D1)**:src 歸戶用 ctags 行區間精確判定;dst 歸戶先套 static 同檔規則(C 語意),殘餘非 static 同名 → 一對多掛靠 + `ambiguous` 註記;查詢輸出分節呈現 |
| FR5 | **邊註記(D3)**:跨引擎觀察寫 `edges.meta`(`ambiguous`/`clangd: confirmed|absent`+hint),confidence 只表達引擎固有準確率,不做跨引擎降級 |
| FR6 | **站點全存(D2)**:一列一站點;動詞層顯示首站點 + 計數,全列走 SQL |
| FR7 | 增量重建(L5):以 `files.content_hash` + git diff 圈出重掃集;改 1 檔重建後與全量重建的圖 diff = 0 |

## 3. 非功能需求

| ID | 需求 |
|----|------|
| NFR1 | 實作 = Python **標準庫 only**;外部依賴僅既有 binary:cscope、universal-ctags(L2+:tree-sitter/clangd/git,各層缺工具時明講跳過,不靜默) |
| NFR2 | 離線可用;不依賴網路與 compile DB(clangd 層例外且為 opt-in) |
| NFR3 | 誠實輸出:超出能力明確標注(P7);寧可漏報絕不誤報 → 誤報風險用 confidence + 標籤暴露 |
| NFR4 | 三層測試(標準庫 unittest):**unit**(歸戶/消歧純函式)、**integration**(fixture 真跑 cscope+ctags 建圖驗 schema 內容)、**e2e**(CLI 全流程驗輸出文字);integration/e2e 在缺 cscope/ctags 時 skip 並明講 |
| NFR5 | git 記錄每一次修改;commit 時測試必須綠 |

## 4. 驗收(design.md §6)

- calls:wpa cflow 28 邊 ≥27、redis 73 邊 = 73(L3 之後)
- fnptr:.scan2 5/5;callback:3 個已知案例全中(L3)
- defs:ctags GT ≥99.5%(L0)
- 12 場景 shootout pin 成測試(誤報防線)
- 增量:改 1 檔重建 < 5s,圖 diff = 0(L5)
