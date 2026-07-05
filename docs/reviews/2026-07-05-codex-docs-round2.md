# 第三方紅隊審查第二輪 — 文件盲區(OpenAI Codex gpt-5.5,2026-07-05)

> 審查對象:requirement.md(Why/What)+ design.md(How)。處置見 design.md §8.6。

## 盲區

1. C++「資訊不漏」和 schema 不相容。`docs/requirement.md:17-20` 承諾 C++ 照收、不漏；但 [docs/design.md:45](/Users/swchen.tw/git/ccodegraph/docs/design.md:45) 的 node kind 沒有 namespace/class/method，`qname` 也只描述 C static 規則。  
   修法：明確降級成「C++ best-effort」或補 C++ 最小合約：namespace、class、method、overload qname、template approximation 規則與驗收 fixture。

2. Token 經濟沒有驗收閉環。`docs/requirement.md:8-15` 說 token 節省是第一因，`docs/requirement.md:60` 又把 LLM 查詢層列為驗收標準；但 [docs/design.md:279](/Users/swchen.tw/git/ccodegraph/docs/design.md:279) 把 R4 放到 L0-L5 完整後。  
   修法：把 R4 提前成早期 spike，定義 5-10 個 agent 任務，量測「無工具 grep/read token」vs「ccodegraph 查詢 token」。

3. Roadmap 把增量放太晚。FR7 在 [docs/requirement.md:59](/Users/swchen.tw/git/ccodegraph/docs/requirement.md:59) 是功能需求，但 L5 在 [docs/design.md:278](/Users/swchen.tw/git/ccodegraph/docs/design.md:278) 才做；同時 [docs/design.md:166](/Users/swchen.tw/git/ccodegraph/docs/design.md:166) 已假設 origin/file 粒度可重掃。  
   修法：先定義 invalidation 模型，特別是 header、macro、include graph、刪檔/改名；否則 L2/L4 寫完後會重做。

4. 「誠實硬需求」和 ambiguous edge 仍有張力。`docs/requirement.md:32-34` 說寧可漏報絕不誤報；D4 在 [docs/design.md:231](/Users/swchen.tw/git/ccodegraph/docs/design.md:231) 只限制 impact 不走，callers 仍顯示候選。  
   修法：文件中區分 `edge`、`candidate_edge`、`user_assertion`；callers 預設可顯示候選，但不得稱為已解析邊。

5. L3 狀態自相矛盾。Layer 3 在 [docs/design.md:161](/Users/swchen.tw/git/ccodegraph/docs/design.md:161) 包含 manual 表，roadmap 又在 [docs/design.md:272](/Users/swchen.tw/git/ccodegraph/docs/design.md:272) 標 L3 完成，但 R1 在 [docs/design.md:274](/Users/swchen.tw/git/ccodegraph/docs/design.md:274) 說 fnptr 人工表補全是下一步。  
   修法：拆成 L3a heuristic done、L3b manual config pending，避免交接者誤判 FR3 已完成。

## 一廂情願

1. C++ 輕量策略缺乏可證偽條件。`docs/requirement.md:17-20` 說不追語意深度但「資訊不漏」，這對 template、overload、macro-generated call 沒有可達成定義。  
   修法：列出 C++ 明確非目標，或把「不漏」改成「保留 parser 可觀測到的符號與近似關係」。

2. callback 0.70 進預設輸出證據太薄。[docs/design.md:95](/Users/swchen.tw/git/ccodegraph/docs/design.md:95) 只有 3/3，[docs/design.md:132](/Users/swchen.tw/git/ccodegraph/docs/design.md:132) 又承認 local shadow 會誤報。  
   修法：把 0.70 標為 provisional；要求 no-local-shadow、def-gate、syntax gate 全通過才進預設，否則低於門檻。

3. `manual confidence=1.0 永遠保留` 把人工輸入當 ground truth。[docs/requirement.md:55](/Users/swchen.tw/git/ccodegraph/docs/requirement.md:55)、[docs/design.md:126](/Users/swchen.tw/git/ccodegraph/docs/design.md:126)。  
   修法：confidence 可為 1.0，但語意應是 `asserted_by_user`，並記錄來源檔 hash、作者、時間；source changed 時標 stale。

4. 效能數字沒有 benchmark 條件。`docs/requirement.md:67` 說 600-800 檔分鐘級；[docs/design.md:158](/Users/swchen.tw/git/ccodegraph/docs/design.md:158) 寫秒級/分鐘級；但沒有硬體、repo、工具版本、冷/熱 cache。  
   修法：新增 benchmark appendix，列固定 repo、commit、機器、命令、p50/p95、DB 大小。

5. SQLite「無壓力」推論不足。[docs/design.md:186-188](/Users/swchen.tw/git/ccodegraph/docs/design.md:186) 用 redis 8 萬列背書，但 [docs/design.md:73](/Users/swchen.tw/git/ccodegraph/docs/design.md:73) 的 `edge_pairs` 是每次 GROUP BY view，索引策略沒有文件化。  
   修法：補索引與 materialized edge_pairs 決策；roadmap 的 backlog 不應只寫在 [docs/design.md:240](/Users/swchen.tw/git/ccodegraph/docs/design.md:240)。

6. GT 數字被當成普遍準確率。[docs/requirement.md:80-81](/Users/swchen.tw/git/ccodegraph/docs/requirement.md:80) 和 [docs/design.md:122-134](/Users/swchen.tw/git/ccodegraph/docs/design.md:122) 把 wpa/redis 結果轉成 confidence。  
   修法：把 confidence 表改成「初始預設值」，附 benchmark 連結與失效條件；不能寫成已證明的通用精度。

## 測試缺口

1. 沒有 FR/NFR traceability matrix。FR1-FR8 在 `docs/requirement.md:53-60`，驗收只有 [docs/requirement.md:78-82](/Users/swchen.tw/git/ccodegraph/docs/requirement.md:78)。  
   修法：新增表格：每個 FR/NFR 對應 unit/integration/e2e/benchmark/人工驗收。

2. FR1 schema 合約沒有 golden test。`docs/requirement.md:53` 要完整列舉欄位與合法值，但 [docs/design.md:67](/Users/swchen.tw/git/ccodegraph/docs/design.md:67) 的 `meta` 是自由 JSON，origin 又在 [docs/design.md:250](/Users/swchen.tw/git/ccodegraph/docs/design.md:250) 說開放集合。  
   修法：加 `schema` golden output、origin registry、meta JSON schema 範例與相容性測試。

3. FR3 manual 表測不到。`docs/requirement.md:55` 要 `registrations` 和 `links`，現有驗收只寫 fnptr 5/5。  
   修法：補 invalid JSON、stale manual、registration fanout、direct link override、manual vs heuristic conflict 測試。

4. FR4 消歧規則測試不完整。`docs/requirement.md:56` 要 src/dst/static/header/ambiguous；[docs/design.md:179-184](/Users/swchen.tw/git/ccodegraph/docs/design.md:179) 有規則，但驗收 [docs/design.md:171-175](/Users/swchen.tw/git/ccodegraph/docs/design.md:171) 沒逐條對應。  
   修法：fixture 至少包含 same-name static、non-static duplicate、static inline header、same basename header、ifdef duplicate。

5. FR5 查詢層缺驗收。`schema/callers/callees/impact/globals/vars-of/who-includes/sql` 在 `docs/requirement.md:57`，但驗收只測 graph 召回。  
   修法：每個動詞建立 golden stdout；特別測 `--min-conf`、ambiguous impact 預設不走、SQL read-only、limit/truncation。

6. FR6 產物集中沒驗收。`docs/requirement.md:58` 要 `.ccodegraph/`、自動 `.gitignore`、路徑可印出。  
   修法：加 e2e：乾淨 repo build 後不得產生 root `cscope.out`，`.ccodegraph/.gitignore` 存在，CLI 顯示所有 artifact path。

7. FR7 增量驗收太窄。`docs/requirement.md:82` 只有「改 1 檔 <5s、圖 diff=0」。  
   修法：補 header 修改、macro 修改、刪函式、rename file、改 manual json、改 compile DB、刪 include 的 normalized diff 測試。

8. wpa/redis GT 代表性不足。`docs/requirement.md:80` 只覆蓋 calls/callback/fnptr 正例；缺 precision、C++、Windows path、macro-heavy、generated code、同名 header、壞工具輸出。  
   修法：GT 分成 recall suite、precision suite、portability suite、failure-mode suite，不要只靠兩個 repo。

## 文件品質(交接視角)

1. D1-D10 分散且 D4/D5 不像正式決策。D1-D3 在 [docs/design.md:177](/Users/swchen.tw/git/ccodegraph/docs/design.md:177)，D4/D5 藏在紅隊處置 [docs/design.md:230](/Users/swchen.tw/git/ccodegraph/docs/design.md:230)，D6-D10 在 [docs/design.md:242](/Users/swchen.tw/git/ccodegraph/docs/design.md:242)。  
   修法：建立單一「決策記錄」表：ID、狀態、決策、理由、反對意見、驗證方式、重估時機。

2. R 編號混亂。`docs/requirement.md:47` 說 VS Code 是 R5，`docs/requirement.md:75` 說 Rust 是 R6；roadmap 有 R1/R2/R4/R5/R6，但沒有 R3。  
   修法：保留 R=research/roadmap 其中一種語意；缺號要寫 retired/reserved。

3. Why/What 混入完成狀態。`docs/requirement.md:80` 寫「已達成,L3」，這不是需求，是進度。  
   修法：requirement 只寫目標；完成狀態放 design roadmap 或 CHANGELOG。

4. 「合法值完整列舉」沒有做到。`docs/requirement.md:53` 承諾完整列舉，但 design 沒有集中列出 node kind、edge kind、origin、confidence range、meta keys 的版本化規範。  
   修法：新增 `Schema Contract Appendix`，把 enum、JSON keys、nullable 欄位語意一次列清楚。

5. `圖 diff = 0` 定義不明。`docs/requirement.md:59`、`docs/requirement.md:82` 都用這句，但 DB 裡有 `created_at/indexed_at/git_rev` 這類 volatile 欄位。  
   修法：定義 normalized graph diff：排除時間戳、排序穩定化、比較 nodes/edges/views 的哪些欄位。

6. 文件缺「失敗時怎麼退化」。NFR1 說缺工具明講跳過 [docs/requirement.md:66](/Users/swchen.tw/git/ccodegraph/docs/requirement.md:66)，P7 說不靜默回空 [docs/design.md:20](/Users/swchen.tw/git/ccodegraph/docs/design.md:20)，但沒有每層缺工具時 schema/query 應呈現什麼。  
   修法：加 degradation matrix：ctags/cscope/tree-sitter/clangd/git 缺失時，哪些 FR 不可用、CLI exit code、schema 顯示內容。
