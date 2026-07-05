# R7 研究:clink(Smattr/clink)— cscope 的現代重實作

> 2026-07-05,source 層研究(clone @ HEAD,depth 1)。建置/實跑結果見文末補記。
> 定位:libclang 語意解析 + SQLite 儲存 + compile_commands.json 原生支援 + TUI/Vim 整合。

## 對我們最有價值的六個洞察

1. **clink 可以直接當我們的填料 origin,零解析程式碼**。它的產出就是 SQLite
   (`.clink.db`),我們 `ATTACH` 之後把 `symbols(category=call, parent)` 翻譯成
   edges(origin=clink)即可——完美示範 D7「整合不重寫」。它吃 compile DB 時
   語意精度接近 clangd,等於 **L4 的替代/補充路線**(比驅動 clangd LSP 簡單得多)。

2. **`parent` 欄位 = 解析期歸戶**。clink 的 symbols 表每筆 occurrence 都帶
   `parent`(enclosing function),由 libclang 在解析時決定——語意級歸戶,
   比我們的「ctags 行區間幾何歸戶」準(macro 展開內的呼叫也歸對)。
   兩者互驗:我們的 D1 幾何歸戶可以拿 clink 的 parent 當 GT 抽查。

3. **byte 級精確範圍**:start/end 的 line+col+byte 六欄。我們只有行級。
   對 R5(VS Code plugin)的精確跳轉,行級不夠,遲早要補 col——schema
   保留欄位的成本低,現在就該想(進 Schema Contract 的保留欄討論)。

4. **records(path, hash, timestamp)= 每檔增量失效**,與我們 L5 的
   files.content_hash 設計相同——獨立收斂,增加信心。

5. **跨語言先例**:asm / MSVC DEF / Python 用模糊解析器,與 libclang 的
   C/C++ 結果共存一個 DB、跨語言呼叫圖——正是使用者「未來接私有組語 flow」
   的架構先例。他們的 asm 解析器(libclink/src/parse_asm*.c)值得細讀。

6. **compile_commands 階梯很簡陋**(db 目錄 → build/ 子目錄,option.c:221),
   不如 ccq 的 Locate→cmake→meson→bear→synthesize 階梯——這塊我們反而領先;
   clink 只解決「有 DB 怎麼吃」,不解決「沒 DB 怎麼生」。

## Schema 對照(clink v1 vs ccodegraph v1)

| 面向 | clink | ccodegraph | 判 |
|---|---|---|---|
| 資料模型 | occurrence 表(symbols+category+parent),查詢時 join 出關係 | 邊表(關係第一等) | 各有理:occurrence 保真、邊表查詢便宜;我們站點全存 = 兩者兼得 |
| 歸戶 | libclang 語意(parent 欄) | ctags 行區間幾何 | clink 準;我們免 build 也能歸 |
| 位置精度 | line+col+byte | line | clink 勝;R5 前補 col |
| provenance | 無(單引擎) | origin+confidence 每筆 | 我們勝——這正是多引擎整合的差異點 |
| 增量 | records.hash+timestamp | files.content_hash(L5 規劃) | 相同思路 |
| 內容快取 | content 表存 ANSI 高亮原始碼行 | 不存(讀原檔) | 我們維持不存:DB 小、原始碼是唯一事實 |

## 建議(入 roadmap)

- **R7a**:clink 作為 L4 級 origin 的 PoC——`clink --build` 產 DB → 匯入器翻譯成
  edges(origin=clink, confidence ~0.93 介於 cscope 與 clangd)。有 compile DB 的
  repo 直接吃到 libclang 精度,不用自己驅動 LSP。
- **R7b**:asm 解析器細讀(parse_asm),對接未來私有組語 flow 的參考實作。
- **Schema v2 討論項**:節點/邊站點加 col(R5 前);目前 v1 不動。

## 補記:建置與實跑(2026-07-05,brew llvm 21 + cmake 4.3.4,Apple Silicon)

建置一次成功(`cmake -B build && cmake --build build`,需 `llvm-config` 於 PATH)。

**category 語意實測確認**(fixture + wpa):`0`=definition、`1`=call(**帶 parent
解析期歸戶**)、`2`=reference(`cmp` 傳參即此類 + parent——對應我們的 callback 訊號)、
`3`=include(帶 include spec 原文)、`4`=**assignment**(對應我們的 writes)。

**關鍵發現:`clink` 的 assignment 偵測抓到了 `counter++`(util.c:13 bump)——
cscope `-L9` 漏掉、我們用 RMW 文字補償才救回的那類,clink 在 libclang 層原生就對。**

**wpa 規模煙霧(620 檔、無 compile DB、libclang fallback)**:CPU ~6.6s(多核並行),
defs 28340 / calls 67460(100% 帶 parent)/ refs 430956 / includes 3396 / assignments 42799。

結論強化:R7a(clink 當 origin)從「值得評估」升級為「高優先」——no-build 下它就
給出解析期歸戶的 calls + 語意級 writes,有 compile DB 則再升精度;匯入器只是
SQL 翻譯(symbols → edges),完全符合 D7。confidence 建議 0.93(no-build fallback
時 0.88,#ifdef 行為與 clangd 同屬單 config 視角,待 GT 實測定案)。

## 補記 2(2026-07-05):no-build 的 libclang 到底能不能用?—— 合成 DB A/B

問題(使用者):compile_commands.json 不一定存在,clink/libclang/clangd 是不是都派不上用場?

**答案:能用,但要給它合成 DB;而且兩種 no-build 模式量的是不同的東西。**

| wpa(620 檔,無 compile DB) | 裸 fallback | 合成 DB(每 .c 一條,-I 蓋全部 header 目錄) |
|---|---|---|
| +calls | 71,403 | 57,953 |
| dropped(歸戶失敗) | 1,679 | **265** |
| semantic absent | 1,091 | **13,895** |
| 耗時 | 5s | 60s |

- **裸模式**:clink 對解析失敗的檔退回模糊解析(README 明載)——全分支、高召回,
  但把它當「語意確認」名不符實(absent 只有 1,091 = 低報)。
- **合成 DB**:真 libclang 單 config 視角——include 解析改善讓歸戶失敗降 84%;
  absent 暴增到 13,895 **不是變差,是誠實**:那正是無 -D 時 config-gated 碼的類別,
  cscope-vs-clangd 二元性(72/73 vs 47/73)的重演。
- 圖是聯集:cscope 全分支層(0.90)完整保留,semantic 層負責「這條在預設 config
  下語意可見嗎」的註記——兩個視角都要,缺一不可(P6)。

**設計落地(D12/D13)**:clink-import 的 compile DB 階梯 = `--compdb a,b,c`
檔案層級合併(first-wins + 衝突逐筆回報)→ root/build 偵測 → **合成(預設)**。
tree-sitter 在此題同樣幫不上:它是純語法,連「單 config 視角」都給不了。
