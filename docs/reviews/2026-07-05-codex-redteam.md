# 第三方紅隊審查 — OpenAI Codex(gpt-5.5,2026-07-05)

> `codex exec --sandbox read-only`,52k tokens。審查對象:docs/design.md、
> docs/requirement.md、idealgraph.py、tests/。處置紀錄見 design.md §8。

## 致命問題

1. **「多引擎全存」在 node 層不成立。**  
   設計宣稱多引擎同一格全存，不合併，查詢層擇優；但 `nodes` 是 `UNIQUE(qname, kind)`，且 `origin/confidence` 只有單值欄位。第二個引擎若發現同一 symbol，沒有地方保存 provenance。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:17)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:50)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:53)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:58)

2. **D1 的非 static 同名「一對多掛靠」會製造 false positive，直接違反「寧可漏報絕不誤報」。**  
   非 static duplicate 會把一個 call 掛到所有候選，`impact` 也會沿著這些假邊擴散。`meta.ambiguous` 只是標籤，不會阻止查詢結果把假候選當邊走。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:13)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:180)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:138)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:279)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:431)

3. **static header function 會被錯誤丟掉。**  
   `choose_dst()` 規則是 static 只能同檔：`c["file"] == site_file`。但 C 裡 `static inline` / header static function 定義在 `.h`，呼叫站點在包含它的 `.c`；這是合法且常見的大型 C repo 模式。現在會把有效 call 判成不可及。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:180)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:138)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:141)

4. **大型 repo 會被 cscope per-symbol subprocess 模式打爆。**  
   L1 對每個 function 跑一次 `cscope -dL3`，每個 global 跑 `-dL0` 和 `-dL9`，每個 header 跑 `-dL8`。數萬檔時不是 SQLite 問題，是數萬到數十萬個 subprocess 問題。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:264)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:270)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:286)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:307)

## 高風險

1. **重建不是原子操作，且會刪舊 DB。**  
   build 直接 `os.remove(db_path)` 再重建；中途失敗會留下沒有圖的 repo，並行查詢會炸。應 build 到 temp DB，完成後 `os.replace()`。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:232)

2. **`cscope.out` 是共享工作目錄產物，並行 build 互相踩。**  
   `cscope -bkR` 固定在 root 產生/覆蓋索引；兩個 build 或使用者自己的 cscope 狀態會競態。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:225)

3. **外部工具錯誤被吞掉。**  
   `run()` 忽略 return code 和 stderr；ctags JSON 失敗會變成空節點，cscope query 失敗會變成空邊，違反 P7。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:18)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:155)

4. **include 歸戶用 basename，遇到重名 header 會錯連。**  
   `headers` 裡如果有 `foo/config.h` 和 `bar/config.h`，兩次都查 `config.h`，結果可能同一批 include rows 掛到兩個不同 header node。大型 repo 幾乎必撞。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:306)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:308)

5. **read/write 分類漏掉 read-modify-write。**  
   `reads = L0 - L9` 用 `(file,line)` 刪 write site；`x = x + 1`、`++x` 會只留下 write，讀取事實消失。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:100)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:290)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:295)

6. **查詢沒有實作預設 confidence threshold。**  
   設計說預設 `confidence >= 0.7`，`impact` 還說每層附信心下限；實作查 callers/callees/impact/globals 都沒用 threshold。未來低信心邊一進表就會被預設查出。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:134)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:143)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:365)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:431)

7. **`edge_pairs` 的 `first_site` 是字串 MIN，不是語意上的第一站點。**  
   `file:10` 會排在 `file:2` 前；跨檔也只是字典序。這會讓使用者看到錯的代表站點。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:74)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:72)

8. **`sql` escape hatch 是可寫 SQL，不是安全查詢口。**  
   目前直接 `con.execute(a.arg)`，沒有 read-only connection、authorizer、只允許 SELECT 的限制。給 LLM/agent 用時，這不是 escape hatch，是破壞 DB 的入口。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:147)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:476)

## 建議

1. 把 node provenance 拆成 `node_observations(node_id, origin, confidence, meta, site/version)`，`nodes` 只放 canonical identity。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:50)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:238)

2. 把 ambiguous edge 從「多條真邊」改成候選集合：例如 `edges.dst` 可空或建 `edge_candidates(edge_id, dst, reason, confidence)`；預設 `impact` 不走 ambiguous。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:280)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:431)

3. cscope query 不要 per symbol subprocess。至少要快取/批次化；更好的方向是解析 cscope 交叉參照或改用單次掃描來源的 parser 層產生候選，再用 ctags/clangd 校正。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:270)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:286)

4. DB 重建改成 temp DB + transaction + atomic replace；cscope index 指到 temp path，避免污染 repo root。  
   證據：[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:225)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:232)

5. 測試補上大型 C repo 真實風險 fixture：重名 header、static inline header、read-modify-write、同檔 `#ifdef` duplicate、macro call、function pointer、callback local shadow、ctags failure、cscope malformed output、multiple call sites。  
   證據：[tests/fixtures/miniproj/main.c](/Users/swchen.tw/git/ideal-graph/tests/fixtures/miniproj/main.c:1)、[tests/integration/test_build.py](/Users/swchen.tw/git/ideal-graph/tests/integration/test_build.py:24)、[tests/e2e/test_cli.py](/Users/swchen.tw/git/ideal-graph/tests/e2e/test_cli.py:23)

## 不同意的決定

1. **原決定：D1 非 static 同名一對多掛靠。**  
   替代方案：建立 ambiguous candidate，不進預設可遍歷 edge；只有查詢明確 `--ambiguous` 才展開。  
   理由：現在是假邊進圖，`impact` 會擴散污染。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:180)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:281)

2. **原決定：D3 跨引擎觀察只寫 meta，不動 confidence。**  
   替代方案：保留 origin 原始分數，但另建 `score` 或 `resolution_state` 給查詢層使用。  
   理由：`clangd confirmed` 和 `clangd absent` 對排序、預設過濾、impact 遍歷都有實際語意，不能只當標籤。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:188)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:331)

3. **原決定：callback confidence = 0.70 且預設門檻也是 0.7。**  
   替代方案：callback 啟發式預設低於門檻，除非 def-gate + callsite syntax + no local shadow 都通過才升級。  
   理由：設計自己承認同名區域變數會誤報，卻讓它剛好進預設輸出。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:130)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:134)

4. **原決定：`sql` 裸 SQL 作為正式查詢動詞。**  
   替代方案：read-only SQLite URI + authorizer 只允許 `SELECT`/`WITH`，另設 `admin-sql`。  
   理由：LLM/agent 場景下，裸 SQL 會把查詢介面變成破壞介面。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:147)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:477)

5. **原決定：redis 8 萬列推論「站點全存 SQLite 無壓力」。**  
   替代方案：站點全存可以保留，但必須搭配 materialized pair table、索引策略和大型 repo benchmark。  
   理由：瓶頸不是 8 萬列，是 `edge_pairs` 每次 GROUP BY 全表、ambiguous 放大、per-symbol subprocess。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:184)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:70)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:365)

## 我認同的決定

1. **站點全存是對的。**  
   缺 callsite 會讓 agent 只能回 grep；`UNIQUE(src,dst,kind,origin,file,line)` 的方向正確，只是需要大型索引與查詢層控制。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:12)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:66)

2. **schema 自省作為第一動詞是對的。**  
   多引擎分層必然有空格子，`schema` 明講 pending 比假裝完整好。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:18)、[idealgraph.py](/Users/swchen.tw/git/ideal-graph/idealgraph.py:381)

3. **file/dir dependency 作為符號邊投影是對的。**  
   不另建一套 file graph 能避免雙重真相；但 view 要修正效能與 edge kind 語意。  
   證據：[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:16)、[docs/design.md](/Users/swchen.tw/git/ideal-graph/docs/design.md:80)

4. **integration/e2e 缺工具時 skip 的原則可接受。**  
   這符合標準庫 only 和離線可用；但 CI 必須至少有一個 job 安裝 cscope + Universal Ctags，否則主功能永遠可能沒跑。  
   證據：[docs/requirement.md](/Users/swchen.tw/git/ideal-graph/docs/requirement.md:28)、[tests/integration/test_build.py](/Users/swchen.tw/git/ideal-graph/tests/integration/test_build.py:24)、[tests/e2e/test_cli.py](/Users/swchen.tw/git/ideal-graph/tests/e2e/test_cli.py:23)

我沒有跑測試；這輪是在 read-only sandbox 下做靜態紅隊審查。
