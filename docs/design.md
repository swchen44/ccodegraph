# ccodegraph — 設計(How)

> Why/What 在 [requirement.md](requirement.md)。本文件是 schema 合約 + 演算法 + 決策記錄。

> 設計依據:三家實測解剖(ccq benchmark 系列,2026-07)——
> **cbm** 的邊分類學 + confidence、**CodeGraph** 的節點分類學 + 邊站點 + token 工程、
> **ccq/cscope** 的 C 召回實測(直接邊 99%、fnptr 5/5、callback 邊)。
> 目標:格子(schema)一次設計到位,料(資料)由多引擎分層填入、逐格標注出處與信心。

## 0. 設計原則(每一條都有實測教訓背書)

| # | 原則 | 來源教訓 |
|---|------|---------|
| P1 | **每條邊帶站點 `file:line`** | cbm 缺格:`UNIQUE(src,dst,type)` 把多呼叫點塌成一條,agent 驗證要回頭 grep |
| P2 | **每條邊帶 `origin` + `confidence`** | cbm 的 `{confidence, strategy}` 是三家最誠實;ccq 鐵律「寧可漏報絕不誤報」→ 不確定的邊要能被過濾而不是被刪除 |
| P3 | **Node = 值得跨函式引用的東西;local 不進圖** | 三家獨立收斂到同一答案(CodeGraph 明寫 top-level、cbm 抽了再濾、ccq def-gate) |
| P4 | **圖是拿來查的,不是拿來看的** | graph.json 太肥的教訓;回傳=函式級去重小答案,不是樹/全圖 dump |
| P5 | **檔案/目錄層 = 符號圖的投影,不另建資料** | CodeGraph `getFileDependents` 歷史 bug 的教訓:file→file 靠 GROUP BY,一份資料多粒度 |
| P6 | **多引擎同一格,全存不合併;查詢層擇優** | 雙引擎互補實證(#ifdef 全召回 72/73 vs config 精度 47/73)——「對」有兩種,不能只留一種 |
| P7 | **超出能力明確報錯/標注,不靜默回空** | cbm Cypher 子集的 `unsupported` 紀律 |
| P8 | **schema 自省是第一個查詢動詞** | cbm `get_graph_schema`:LLM 進來先問「圖裡有什麼格、填了多少」 |

## 1. Schema(sqlite)

```sql
-- ============ 出處層(整張圖的 provenance)============
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- schema_version, root, git_head, created_at, tool_versions(JSON),
-- engines_run(JSON: [{engine, version, files, seconds}]), compile_db(路徑|synthesized|none)

CREATE TABLE files (
  path        TEXT PRIMARY KEY,   -- repo 相對路徑
  lang        TEXT,               -- c | cpp | header | ...
  content_hash TEXT,              -- 增量重建的失效單位(cbm file_hashes 教訓)
  indexed_at  TEXT,
  git_rev     TEXT                -- 此檔最後索引時的 commit
);

-- ============ 節點 ============
CREATE TABLE nodes (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  qname     TEXT NOT NULL,        -- 消歧名:file-scope static → "path/file.c::name",全域 → "name"
                                  -- (C 的同名 static 是 cscope/ctags name-key 的最大誤差源)
  kind      TEXT NOT NULL,        -- function | global | macro | struct | union | enum
                                  -- | enum_member | typedef | file
                                  -- (file 進 nodes 是為了 includes 邊;dir 不進——投影即可)
  file      TEXT NOT NULL REFERENCES files(path),
  line_start INTEGER, line_end INTEGER,
  signature TEXT,                 -- 函式簽名 / 變數型別(clangd/ctags 可填,允許 NULL)
  is_static INTEGER DEFAULT 0,    -- C 的 file-scope
  origin    TEXT NOT NULL,        -- 誰發現這個定義:ctags|cscope|treesitter|clangd|cindex
  confidence REAL NOT NULL,       -- 定義本身的信心(見 §3 分數表)
  metrics   TEXT DEFAULT '{}',    -- JSON 後填欄:loc, cyclomatic, fan_in/out(cbm 維度,允許空)
  UNIQUE(qname, kind)
);

-- ============ 邊(一列 = 一個站點;pair 級視圖見下)============
CREATE TABLE edges (
  id      INTEGER PRIMARY KEY,
  src     INTEGER NOT NULL REFERENCES nodes(id),
  dst     INTEGER NOT NULL REFERENCES nodes(id),
  kind    TEXT NOT NULL,          -- 見 §2 邊分類學
  file    TEXT, line INTEGER,     -- 站點:呼叫/分派/讀寫/include 發生處(P1)
  origin  TEXT NOT NULL,          -- cscope|treesitter|clangd|fnptr|callback-heur|manual|git
  confidence REAL NOT NULL,       -- 見 §3
  meta    TEXT DEFAULT '{}',      -- JSON:fnptr 的 (struct,field)、git 邊的共變次數等
  UNIQUE(src, dst, kind, origin, file, line)   -- 多站點=多列;同站點多引擎=多列(P6)
);

-- ============ 查詢層視圖(LLM 實際打的面)============
-- pair 級去重:同 (src,dst,kind) 取最高信心 + 首站點 + 聚合 origins
CREATE VIEW edge_pairs AS
  SELECT src, dst, kind,
         MAX(confidence)               AS confidence,
         MIN(file || ':' || line)      AS first_site,
         COUNT(*)                      AS site_count,
         GROUP_CONCAT(DISTINCT origin) AS origins
  FROM edges GROUP BY src, dst, kind;

-- 檔案級投影(P5):A 檔依賴 B 檔 = 符號邊 roll-up
CREATE VIEW file_deps AS
  SELECT DISTINCT e.file AS src_file, n2.file AS dst_file, e.kind
  FROM edges e JOIN nodes n2 ON e.dst = n2.id
  WHERE e.file IS NOT NULL AND e.file != n2.file;
```

## 2. 邊分類學(每一種都標「誰能填、C 上的實測期望」)

**第一層:呼叫家族**(核心,已全部實測過)

| kind | 語意 | 填入引擎(→§3 分數) | C 實測期望 |
|---|---|---|---|
| `calls` | 直接呼叫 | cscope -dL3 / ts / clangd | 26/28、72/73(cscope);clangd 依 config |
| `callback` | 函式當參數傳遞 | regex 啟發式(前後字元規則) | cscope 全滅的那 3/3;wpa 27/28 的關鍵 |
| `fnptr` | ops/vtable 分派 | fnptr 啟發式 + `manual` 人工表 | 5/5;manual 邊 confidence=1.0 永遠保留 |

**第二層:狀態家族**(cbm 有、CodeGraph 沒有、我們已用 cscope 做出來)

| kind | 語意 | 填入引擎 |
|---|---|---|
| `reads` | 函式讀全域 | cscope -dL0(− L9) |
| `writes` | 函式寫全域 | cscope -dL9 |

**第三層:結構家族**

| kind | 語意 | 填入引擎 |
|---|---|---|
| `includes` | file → file(`#include`) | cscope -dL8(C 獨有的直接訊號,cbm/CodeGraph 都沒有) |
| `uses_type` | 函式 → struct/typedef | clangd(精確)/ ts(近似);**phase 2,格子先留** |
| `expands` | 函式 → macro(使用巨集) | cscope -dL0 對 macro 節點;cindex 供 macro 定義 |

**第四層:時間家族**(git,cbm 的 `FILE_CHANGES_WITH` 維度——你點名的增量方向)

| kind | 語意 | 填入來源 |
|---|---|---|
| `co_changes` | file ↔ file 常一起改 | `git log --name-only` 共變統計;meta 存次數與視窗 |

**刻意不做**(P7,寫進 schema 自省的回答裡):`SIMILAR_TO`/embedding(偏離任務)、
跨服務 HTTP/channel 邊(C 場景少)、`contains`(= nodes.file 欄位的投影,不佔邊表)。

## 3. Confidence 分數表(不是拍腦袋——每格對應一個實測數字)

| origin | 填的邊 | confidence | 依據 |
|---|---|---|---|
| `manual`(ccq.fnptr.json) | fnptr | **1.00** | 人工 ground truth,鐵律永遠保留 |
| `clangd`(有真實 compile DB) | calls/uses_type | **0.95** | 場景 12/12;但單 config 視角(漏 inactive 分支是特性不是錯) |
| `cscope` | calls/reads/writes/includes | **0.90** | 26/28、72/73、99.2% defs;name-keyed 誤差(同名 static) |
| `cindex/regex` | calls/callback 的 def-gate | 0.90 | 99.7% defs |
| `treesitter` | calls(聯集補充) | **0.85** | 聯集淨賺 +7/+17 defs;獨立 52% → 只當補充源 |
| `fnptr` 啟發式 | fnptr | 0.80 | 5/5 但 FANOUT_CAP 下的近似 |
| `callback` 啟發式 | callback | **0.70** | 同名區域變數會誤報(documented approximation) |
| `clangd`(synthesized no-build DB) | calls | 0.75 | 缺 -D,inactive #ifdef 不可見 |
| `git` | co_changes | 0.5×歸一化共變頻率 | 統計訊號,不是語意 |

查詢預設回 `confidence >= 0.7` 並標 origins;`--all` 掀開全部。
**漏報用聯集治(多引擎全存),誤報用標籤治(讓 LLM 看見信心)——兩個鐵律同時成立的機制。**

## 4. 回傳層(動詞,不是查詢語言;SQL 當逃生口)

```
schema                      ← 第一動詞(P8):各 kind 節點/邊數、各 origin 填充率、
                              哪些格子是空的(「uses_type 尚未填:需要 clangd + compile DB」)
callers X / callees X       ← pair 級去重 + [origins] 標籤 + 首站點 @ file:line
impact X -d N               ← 遞迴 CTE,只走 calls|fnptr|callback,附每層信心下限
globals V / vars-of F       ← reads/writes 拆開列
who-includes H              ← includes 邊
co-changed F                ← git 時間家族
sql '...'                   ← 裸 SQL(P4 的自助逃生口)
```

輸出格式沿用實測贏過的形狀:一行一筆、函式級、`name @ file:line [origins]`,
多義符號分節(CodeGraph #764 教訓),超過 limit 明講截斷(P7)。

## 5. 填料計畫(分層,每層獨立可驗收)

```
Layer 0  ctags       → nodes(function/global/…)             秒級   ← 骨架
Layer 1  cscope      → calls/reads/writes/includes 邊        ~1-2 分 ← 地板(已有 cscope_graph.py 原型)
Layer 2  tree-sitter → calls 聯集補充、K&R/宣告子巢狀 defs     ~秒級
Layer 3  fnptr/callback 啟發式 + manual 表 → 間接呼叫家族     秒級   ← 對 LLM 最值錢的一層
Layer 4  clangd(有 compile DB 才跑)→ 高信心 calls/uses_type/signature 升級  分鐘級
Layer 5  git log/diff → co_changes 邊 + files.git_rev(增量失效的基礎)
```

每層寫入時只動自己 origin 的列(`DELETE WHERE origin=X AND file IN (changed)` → 重掃),
天然支援「某引擎單獨重跑」與 git 增量(files.content_hash + git diff 圈出重掃集)。

## 6. 驗收(沿用既有 GT,一開始就掛閘)

- calls:wpa cflow 28 邊 ≥27、redis 73 邊 = 73(聯集後)
- fnptr:.scan2 5/5;callback:3 個已知案例全中
- defs:ctags GT ≥99.5%
- 誤報抽查:string_fake_call 等 12 場景 pin 成測試(shootout 方法論)
- 增量:改 1 檔重建 < 5s,圖與全量重建 diff = 0

## 7. 已拍板的三個決定(2026-07-04)

**D1 同名符號 → 分節呈現(CodeGraph 模式);歸戶在圖層做,不靠 cscope。**
cscope 是 name-keyed,但圖層有 ctags 的定義行區間 + 邊的站點 file:line:
- **src 歸戶 = 精確判定**:站點 file:line 落在哪個同名定義的 [line_start, line_end] 內。
- **dst 歸戶分兩級**:(a) `static` 同檔規則——C 語意保證 file-scope static 只能被同檔呼叫,
  ctags 知道 is_static,吃掉多數同名案例;(b) 非 static 同名(eloop.c/eloop_win.c 型的
  二選一連結)→ 一對多掛靠 + `meta.ambiguous` 註記(見 D3)。

**D2 站點全存。** `UNIQUE(src,dst,kind,origin,file,line)` 維持一列一站點;
`callers`/`callees` 動詞預設顯示首站點 + `(N sites)` 計數,全列用 SQL 撈。
redis 全圖約 8 萬列,sqlite 無壓力;靜默截斷違反 P7。

**D3 跨引擎資訊 → 邊上註記(meta JSON),不動 confidence。**
confidence 只表達「產生引擎的固有準確率」(§3 分數表);跨引擎的觀察寫進 meta,
由查詢動詞翻成標籤,判讀交給 LLM:

```json
{"ambiguous": true, "candidates": 2, "rule": "non-static-dup"}
{"clangd": "confirmed"}
{"clangd": "absent", "hint": "inactive-ifdef-or-wrong-candidate"}
{"clangd": "confirmed", "resolved_ambiguity": true}
```

輸出範例(分節 + 標籤):

```
callers of eloop_init — 2 個定義,分節:

## eloop.c:145 的定義  [cscope, clangd✓]
- main @ main.c:201

## eloop_win.c:98 的定義  [cscope; clangd 未見:可能是未編譯的平台分支]
- main @ main_winsvc.c:88
```

理由:「clangd 沒看到」在 #ifdef 情境是重要線索(另一 config 的碼)、在同名情境是
消歧依據——註記保留兩種解讀,降分會把資訊吃掉。

## 8. 第三方紅隊審查處置(2026-07-05,codex gpt-5.5)

完整報告:[reviews/2026-07-05-codex-redteam.md](reviews/2026-07-05-codex-redteam.md)。處置:

**採納並已修(無衝突項):**
- 原子性重建:build 寫 `.building` temp → `os.replace`(致命後果:半成品 DB)
- cscope 索引隔離:專用 `.ideal-graph.cscope.out`,不污染使用者的 cscope.out
- 外部工具失敗大聲死(`run_checked`,P7)
- **static inline in header**:`choose_dst` 加 header 例外(codex 致命問題 3,真 bug)
- 重名 header 錯連:includes 邊比對 `#include` 內容與 header 路徑後綴
- read-modify-write:`x++`/`x+=`/`x=x+1` 站點雙向補償(reads↔writes,meta.rmw)
- 查詢門檻落地:`--min-conf`(預設 0.7)進所有動詞
- `sql` 動詞改唯讀連線(`mode=ro`);`first_site` 改可排序編碼

**使用者裁決(2026-07-05,三題皆選折衷/維持):**
- **D4**:ambiguous 邊 **callers 顯示(帶標籤)、impact 預設不走**,`--ambiguous` 全開
  ——codex「假邊污染 impact」的攻擊成立,但全隱藏會讓 LLM 看不見雙候選事實
- **D5**:callback confidence **維持 0.70、預設含 + [callback] 標籤**
  ——實測 3/3 中、未見誤報;它是 cscope/clangd 全滅的最值錢邊,不因理論風險降級
- **D3 維持**(meta-only,不加 resolution_state 欄)——L4 clangd 實作時以實際資料重估

**認列 backlog(不阻擋):**
- per-symbol subprocess 規模化(cscope -dl 常駐模式 / 批次)——數萬檔 repo 才會痛
- node 層多引擎 provenance(`node_observations` 表)——L2 落地時一併
- `edge_pairs` 物化 + 大 repo benchmark;CI job(裝 cscope+ctags 跑 integration)

## 8.5 定位決策(2026-07-05,使用者拍板;取捨原因是交接資產)

**D6 改名 ccodegraph,C 80% / C++ 20% 輕量。**
為什麼:真實工時 80% 在 C(no-build 韌體/驅動);C++ 只求資訊不漏(照收、標 origin),
語意深度交給 clangd 層。取捨:不為 20% 場景引入重型 C++ 解析,速度與輕量優先。

**D7 整合既有工具,不重寫解析器。**
ctags/cscope/tree-sitter/clangd/clang AST 都是數十年引擎;我們的價值 = 組合 + 歸戶 +
消歧 + 標注。origin 是開放集合——未來私有工具(組合語言級 flow)接入只是新增一個
origin 值與 confidence 行,不改 schema。實測背書:cscope 直接邊 99% 級召回,自寫到不了。

**D8 Schema 是合約,轉換是另一件工作。**
Schema 必須自足到「LLM 只讀 schema 就會用」;填料引擎(哪個工具、哪種語言寫)
可以整組換掉而合約不動——這也是 R6(Rust 移植)不影響現在任何決定的原因。

**D9 產物集中 `<root>/.ccodegraph/`。**
ccq 經驗直接繼承:graph.db、cscope.out、自動 `.gitignore` 全在一個專案層目錄,
不污染使用者空間;未來若有 user 層狀態(daemon 等)放平台 cache dir,
但**所有路徑必須可印出**——「不要隱藏」是使用者明示原則。

**D10 分工哲學(寫給未來的查詢層,R4)。**
重複機械工作 → 固定程式;LLM → 高階判斷(選工具、選資料、解讀含糊訊號)。
圖譜提供基本 AST 級資訊;LLM 拿 `file:line` 精確讀碼是最後手段、不是起手式。

## 9. Roadmap(進度總覽;完成的打勾,順序即計畫)

| # | 項目 | 狀態 | 備註 |
|---|------|------|------|
| L0 | ctags 節點 + qname 消歧 | ✅ 2026-07-05 | wpa 10605 節點 |
| L1 | cscope 邊(calls/reads/writes/includes) | ✅ 2026-07-05 | 單層 26/28 |
| L3 | callback + fnptr + manual 表 | ✅ 2026-07-05 | **wpa 28/28 + fnptr 5/5** |
| — | ruff/mypy strict + 三層測試 + codex 紅隊處置 | ✅ 2026-07-05 | 75 tests |
| R1 | **fnptr 人工表補全**:ccq.fnptr.json 血統的 `registrations`(使用者指定 struct/field → handler)+ `links`——**使用者可設定參數是既有承諾,必須保留**;manual 邊 confidence 1.0 永遠保留 | ⬜ 次一步 | L3 收尾 |
| R2 | **ctags 跨平台相容**:macOS(BSD ctags)/Linux(Exuberant)/Windows 參數差異——啟動偵測 flavor、參數對映表、非 Universal Ctags 時大聲死 + 安裝指引;CI 三平台矩陣 | ⬜ L2 前必須 | BSD ctags GT 污染是 ccq 時代已踩過的坑 |
| L2 | tree-sitter 聯集 builder(K&R/宣告子巢狀 defs) | ⬜ | origin=treesitter, 0.85 |
| L4 | clangd 升級層(confirmed/absent 註記、signature、uses_type;需 compile DB) | ⬜ | D3 在此重估 |
| L5 | git 層(co_changes 邊 + content_hash 增量;改 1 檔 <5s、圖 diff=0) | ⬜ | |
| R4 | **查詢層設計(獨立階段,L0–L5 完整後)**:LLM 導向動詞 + SKILL.md(沿用 ccq 經驗:token 形狀、分節、標籤、schema 自省為第一動詞)——「重點是讓大語言模型知道如何使用」 | ⬜ 等完整 DB | 現有動詞是工程驗證用,非最終介面 |
| R5 | VS Code plugin(友善 UI 讀同一份 graph.db) | ⬜ 最後 | 應用層;DB 是唯一事實來源,plugin 只是另一個 reader |
| R6 | Rust 移植研究(傳聞 10x;等功能完整 + schema 穩定) | ⬜ 研究項 | D8:合約不動,引擎可換 |
| — | 改名 ccodegraph + 產物歸位 .ccodegraph/(D6/D9) | ✅ 2026-07-05 | |
