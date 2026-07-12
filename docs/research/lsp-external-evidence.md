# 外部證據 vs v6:為什麼別人說 LSP 很好,而我們測出 60=60(2026-07-13)

> **TL;DR**:兩邊都對——戰場不同。外部的「LSP 效果很好」集中在
> **編輯迴路**(改碼後即時診斷、重構後 build 必過、生成時防幻覺 API)、
> **grep 弱勢語言**(TypeScript/Java:無 header 宣告慣例、同名 overload
> 多)、**大 repo**(36K-149K 行起跳);我們 v6 測的是**唯讀導航問答 ×
> C 語言 × 中型 repo**——C 是 grep 最強的語言(header 慣例 + `#include`
> 文字可見 + 巨集是所有結構化工具的共同死角),而且題目自帶範圍限定。
> 兩個獨立互證:①社群裝了 LSP 後最常見抱怨就是「Claude 還是只用
> grep」,與我們 36% 零使用完全一致;②他們的解法(CLAUDE.md 寫
> 「prefer LSP」)正是我們 hint-probe 實測無效的那招。人類用 cscope
> 比 grep 省心,是因為人的成本函數是互動延遲+心智負擔;agent 的成本
> 函數是 token+錯誤率,而它 grep 不會累——「省心省力」在 agent 側
> 大幅貶值。

## 1. 外部主張的分類與原始證據

### A. 編輯迴路(LSP 真正的主場;v6 沒測)

- **ManoMano 對決**(Java 36K 行/381 類,vanilla Claude vs Claude Code
  內建 LSP vs Serena,N=1 手動):**大型重構任務**(抽 record + 改全部
  使用點 + build 必過)——Serena 45min/$27.30 **1,017 測試全過**;
  內建 LSP 1h/$28.63 留 9 個測試失敗;vanilla 1h/$23.54 直接失敗。
  但**快速探索任務 Serena 反而貴 4 倍慢 60%**。同場觀察:內建 LSP
  「hallucinated and mixed up methods with the same name」——與我們
  的 26% 空/錯呼叫、靜默不完整同族。
- **CircleCI 實測**(TypeScript,Vue.js core ~149K 行):列的價值主張
  一半在編輯側——**改碼後毫秒級診斷**(type error/missing import)、
  safe rename、防呼叫不存在的函式。
- **Monitor-Guided Decoding(NeurIPS 2023,microsoft/multilspy)**:
  LSP 靜態分析接進**解碼過程**,防生成幻覺符號、提升可編譯率——
  收益在「寫」不在「查」。

### B. 導航,但在 grep 弱勢語言 + 大 repo

- CircleCI 的導航數字(TypeScript 149K 行):LSP 全對,**grep 臂真的
  漏引用**(`trigger` 11 個漏 2、`effect` 260 個漏 11),LSP 還省
  14-33% token。**這是與 v6 相反的結果**——但語言是 TS(動態 import、
  re-export 鏈、無 header),規模 149K 行,漏報是 grep 的真實風險。
  同文自承:「小專案 grep 就好」、language server 吃數 GB、monorepo
  冷啟動要分鐘級。
- **cbm 論文**(arXiv 2603.27277,tree-sitter 知識圖,31 語言):
  對 grep 臂 90% 相對正確性但 **token 省 10 倍**;自承 **C 語言品質
  0.58**(滿分 1)——「巨集不在 tree-sitter AST」。**C 的靈魂是巨集,
  恰是一切結構化工具的共同死角、grep 的主場**(我們 v1 的 D11:wpa
  有 586 個被呼叫的函式型巨集;ccodegraph 的 expands 維度就是為此
  而生)。
- Serena(oraios/serena,LSP-based MCP,20+ 語言):主打 symbol 級
  檢索+編輯的 token 效率;社群回饋「省的是大 codebase、長 session、
  重複 symbol 編輯」,小場景反被 MCP 工具描述的固定 token 開銷吃掉。

### C. 體驗文與其局限

- 「30 秒 grep → 50ms、900× 快」類文章:那是**單查詢延遲**,不是任務
  正確性;且多為 N=1 教學文,無對照、無評分。
- **社群最常見抱怨(關鍵互證)**:「even with LSP fully set up,
  Claude Code may default to its familiar tools (Grep, Read, Glob)」
  ——與 v6 的 36% 零使用、Bash 342 vs LSP 117 完全一致;社群解法
  (CLAUDE.md 寫 prefer-LSP)正是我們 hint-probe 以 9 runs 實證
  「單句無效」的那招,而 SKILL 級教學也只買到使用**更準**(call
  hierarchy 5→26 次)不買到分數。

### D. 業界反方:Claude Code 自己的立場

Boris Cherny(Claude Code 作者)公開說明:早期版本用過 RAG+向量庫,
實測後**改為純 agentic grep**——更精確(exact match vs fuzzy)、
無索引 staleness、無隱私問題、簡單。**整個 Claude Code 的工具肌肉
記憶就是圍繞 grep 調教的**——這從訓練分佈層面解釋了「LSP 在場也
不用」:工具先驗是 grep-first,單句 prompt 撼不動(hint-probe 實證)。
SWE-agent(NeurIPS 2024)的 ACI 論文同一結論的正面版:**介面設計
(工具怎麼呈現給 agent)比工具本身更影響表現**——我們 v3→v6 四次
驗證的教學層效應,是它的一個實例。

## 2. 差異矩陣:他們的場景 vs 我們的 v6

| 維度 | 外部正面報告 | 我們 v6 | 誰對? |
|---|---|---|---|
| 任務 | 編輯/重構/生成(diagnostics 迴路) | 唯讀導航問答 | 都對——LSP 主場在編輯迴路,v6 沒測 |
| 語言 | TS/Java/多語言(grep 弱) | C(grep 最強:header 慣例、巨集) | 都對——語言決定 grep 基線高度 |
| 規模 | 36K-149K 行、monorepo | 620/784 檔、題目帶範圍限定 | 都對——grep 線性成本在大 repo 才爆 |
| 方法 | 多為 N=1 體驗/教學文 | N=3 + 獨立評分 + 零回歸稽核 | 受控結論以 v6 為準,但適用域要標清楚 |
| 「裝了不用」 | 社群頭號抱怨 | 36% 零使用 + hint 無效 + SKILL 只改組成 | **完全互證** |

## 3. cscope 對人類省心 ≠ 對 agent 省分:成本函數不同

人類:每次查詢付**互動延遲 + 打字 + 心智負擔 + 結果篩選**;grep 會
让人偷懶少查、漏查,cscope 把這些成本砍掉,所以「一定省心省力」。
Agent:成本函數是 **token + turn 數 + 錯誤率**;它的 grep 是機器速度、
正則熟練、讀 260 個檔案不喊累、且(教學後)有覆核紀律——人類的偷懶
錯誤它不犯。省心的價值在 agent 側大幅貶值,剩下能買的只有「省 token」
與「防漏報」:前者在中型 C repo 只值 ~16%(v6 實測 lsp 比 none 貴,
cbm 論文的 10× 省是在無範圍限定的大庫題型),後者在 C 上 grep 本來就
少漏(v6:none 60/66)。**同一把刀,對不同的手值不同的錢。**

## 4. 對我們的三個校準

1. **v6 結論的適用域聲明**(已回寫報告總結論的語境):「out-of-box
   LSP = grep」成立於 *C × 唯讀導航 × 中型 repo × 題帶範圍*;不可
   外推到編輯迴路、TS/Java、149K+ 行。外部正面經驗大多來自後者,
   與 v6 **不矛盾**。
2. **若有 v7,真正未測的戰場是編輯迴路**:重構+build 必過型任務
   (ManoMano 式),那裡 diagnostics 是 LSP 的不對稱優勢——也是
   ccodegraph 完全沒有的能力,誠實列為它的域外。
3. **ccodegraph 定位再聚焦**:cbm 自承 C 巨集 0.58、LSP 單 config、
   Claude Code 官方 grep-first——三方證據共同指向同一個縫隙:
   **大型 C 專案的巨集/多 config/includes 枚舉**是結構化工具裡
   只有 ccodegraph 認真做的區域;而「中小 repo 導航」這個區域,
   官方 grep 已經夠好,不是戰場。

## FAQ(2026-07-13,使用者提問實錄)

### Q1:LSP 好處在寫碼,是什麼原理?

四個機制:

1. **編輯後即時診斷(最大宗)**:LSP 的 `publishDiagnostics` 通道——
   agent 每做一次 Edit,語言伺服器毫秒級重新做型別/語意檢查,錯誤
   **直接推進 agent 的 context**(Claude Code plugin 的 `diagnostics`
   欄位預設 true 就是這個)。原理是**回饋迴路的週期壓縮**:沒有它,
   要等 build/test(分鐘級)才知道改壞,且錯的 edit 讓後續 edits 疊在
   錯誤上——錯誤有複利;有了它,每個 edit 的錯當下被抓、不累積。
   ManoMano 重構 1,017 測試全過 vs 內建 LSP 留 9 個失敗,差的就是
   這條迴路的品質。
2. **生成時約束(MGD,NeurIPS'23)**:LLM 逐 token 生成時用 LSP 查
   「此位置合法的成員/方法集合」,把下一個 token 限制在合法集合內
   ——結構上不可能拼出不存在的 API。靜態分析當解碼約束器。
3. **語意閉包操作**:rename/改簽名是全域一致性問題,LSP 一次改對
   所有引用(含跨檔與同名消歧);文字替換必然漏改或誤傷。
4. **為什麼「寫」比「讀」受益大**:讀的錯誤=漏一條引用(扣一分);
   寫的錯誤=build 壞(二值失敗)。且驗證成本不對稱:讀的答案要 GT
   才能驗,寫的結果 diagnostics 免費當裁判——**LSP 在寫碼側等於
   白送一個毫秒級裁判**,這是它在導航問答側沒有的角色。

### Q2:「快」不也是優點?找 code flow 時 grep 要讀檔迭代,問 ccodegraph 直接列出來,理論上快很多,難道不是?

**單查詢延遲層:完全正確**——`callers X` 一次 SQL 毫秒級,grep 追鏈
是「grep→讀→再 grep」多輪。外部的「30s→50ms、900×」講的就是這層。

**任務總時間層:被兩個效應吃掉**(v6 實測):

| | wall 中位 | turns 中位 |
|---|---|---|
| none(grep) | 39s | 6 |
| ccodegraph | 49s | 9 |
| WRQ-008 呼叫鏈題 | none 76-107s(16-23 turns) | ccodegraph 78-103s(**14-18 turns**) |

呼叫鏈題上 ccodegraph turns 確實較少(工具優勢真實),但牆鐘打平:

1. **任務時間 ≈ turns × LLM 推理延遲,工具執行是零頭**——每 turn
   模型思考 3-6 秒,工具 50ms 或 30s 只是零頭,大頭在模型腦子裡。
2. **省下的預算被紀律再投資**:SKILL 教的交叉驗證/讀 cited lines 把
   省下的 turns 拿去覆核而不是提早交卷——**速度紅利被轉換成正確性
   紅利**(+3 分的來源)。要快就得砍覆核,分數就掉;是取捨不是損失。

**直覺會兌現成真快的三個條件**:①鏈更深(題庫鏈深 ~3-5 層差距小,
八層十層的 kernel 級鏈才拉開;v5 上 ccodegraph token 已省 17% 是規模
兌現的訊號);②庫更大且題無範圍限定(grep 每輪全庫掃描 token 線性
增長、圖查詢輸出恆定——cbm 的 10× token 差在這個 regime);③人在等
的互動場景(50ms vs 30s 的體感是人類「省心」的主體,批次 agent 任務
中被稀釋)。

一句話:**「快」的兌換率取決於瓶頸在哪**——瓶頸在搜尋輪次(深鏈/
大庫/無範圍)時兌現為速度;瓶頸在模型推理時兌現為「多出來的覆核
預算」,也就是分數。v6 屬於後者。

## Sources

- [ManoMano: Benchmarking AI Coding Agents (Claude vs Claude Code vs Serena, 36K Java)](https://medium.com/manomano-tech/project-aegis-benchmarking-ai-agents-and-why-serena-is-our-new-must-have-311673db35dd)
- [CircleCI: Why you should use LSP with Claude Code(Vue.js 149K 行實測)](https://circleci.com/blog/claude-code-lsp/)
- [Codebase-Memory 論文(arXiv 2603.27277;cbm,即 v3/v5 受測工具)](https://arxiv.org/html/2603.27277v1)
- [Monitor-Guided Decoding(NeurIPS 2023)+ microsoft/multilspy](https://github.com/microsoft/monitors4codegen)
- [SWE-agent: Agent-Computer Interfaces(NeurIPS 2024)](https://arxiv.org/abs/2405.15793)
- [oraios/serena(LSP-based MCP toolkit)](https://github.com/oraios/serena)
- [Building Claude Code with Boris Cherny(Pragmatic Engineer;agentic grep 取代 RAG 的設計決策)](https://newsletter.pragmaticengineer.com/p/building-claude-code-with-boris-cherny)
- [Claude Code Doesn't Index Your Codebase](https://vadim.blog/claude-code-no-indexing/)
- [aider: Building a better repository map with tree-sitter(ctags→tree-sitter 路線)](https://aider.chat/2023/10/22/repomap.html)
- [Scott Spence: Enable LSP in Claude Code](https://scottspence.com/posts/enable-lsp-in-claude-code)、[resolvewith.me: 30s→50ms](https://resolvewith.me/blog/claude-code-lsp-code-navigation-50ms)(體驗文代表;「裝了不用」抱怨出處)
- 內部對照:`llm-ab-v6-lsp.md`(v6 全弧)、`llm-ab-v5-linux-kernel.md`、`cscope-query-engine-bugs.md`
