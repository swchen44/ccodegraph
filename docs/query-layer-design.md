# R4:查詢層設計(for LLM)— v0 草案

> 前提已成立:L0–L5 全數完工,graph.db 是完整的(nodes 4 kinds、edges 8 kinds、
> origin 6 種、semantic 註記、增量對齊)。本設計回答 FR8/FR9:
> **驗收標準 = 「讓大語言模型知道如何使用」**。

## 1. 設計原則(繼承 + 新增)

- **P4 圖是拿來查的**:每個動詞回小答案;整圖 dump 永遠不是介面。
- **D10 分工**:機械歸戶/去重/聚合在動詞裡做完;LLM 只做判讀。
- **R4-1(新)風險語意是教材不是註腳**:SKILL.md 必須明講三層判讀材料
  (confidence 數字、origin 出身、semantic 標籤)與其風險含義——
  使用者 2026-07-05 拍板:「必須把這個風險跟大語言模型講,那它可以識別」。
- **R4-2(新)雙軌輸出(FR9)**:每個動詞 `--json`;文字省 token、JSON 給
  程式化消化,**由 LLM 自行選**;兩者欄位一一對應,JSON schema 入 Schema Contract。

## 2. SKILL.md 大綱(交付物;沿 ccq/cscope/clangd 三份 skill 的成功模式)

```
frontmatter:觸發詞(誰呼叫/who calls/impact/全域變數/巨集/#ifdef...)+ 範圍界定
The journey:build → (clink-import) → 查詢;改碼後 build --incremental
Step 0:schema —— 先看格子與填充率、engines_run 出身、STALE 警告
動詞參考表:何時用哪個動詞、預設門檻、--ambiguous、--json
★ 風險判讀章(R4-1,本 skill 的核心差異):
   confidence 表:0.95 真DB clink / 0.93 合成DB / 0.90 cscope / 0.80 fnptr
                 / 0.70 callback / 0.50 git —— 每級「錯的方式」是什麼
   origin 並列 = 多引擎背書;單一 origin 時该信誰、怎麼驗
   semantic:absent ≠ 假邊 —— 是「預設 config 下不可見」(#ifdef 線索)
   ambiguous 標籤 = 同名多定義的一對多掛靠;impact 預設不走、如何全開
   manual = 使用者斷言(asserted_by_user);STALE 警告出現時先重建
盲點表(誠實):巨集生成定義看不見(除非 clink+真DB)、name-keyed 近似、
   C++ 輕量(W3)、合成DB 無 -D
SQL 逃生口:schema DDL + 三個範例查詢(唯讀)
```

## 3. 動詞最終形狀(現有動詞升級,非重寫)

| 動詞 | 升級點 |
|---|---|
| `schema` | 已是第一動詞;補 engines_run 模式與 STALE 顯示的穩定格式 |
| `explore X`(新) | 一發:定義(signature+file:line)+ callers + callees + 讀寫的全域 + 用的巨集——ccq 實測的頭牌動詞,token 最省的一次呼叫 |
| `callers/callees/impact/globals/vars-of/who-includes/co-changed` | 全部加 `--json`;輸出行統一 `name @ file:line (N sites) [origins; tags]` |
| `sql` | 唯讀已就位;SKILL 教 3 個模板查詢 |

## 4. `--json` 形狀(FR9;與文字欄位一一對應)

```json
{"verb": "callers", "symbol": "eloop_init", "definitions": [
  {"qname": "eloop.c::eloop_init", "file": "...", "line": 145,
   "callers": [{"qname": "main", "site": "main.c:201", "sites": 1,
                "origins": ["cscope", "clink"], "confidence": 0.95,
                "tags": {"semantic": "confirmed"}}]}],
 "truncated": false, "min_conf": 0.7}
```

## 5. 驗收

- **真 LLM A/B**(R4a 的正式版,ccq token-cost 方法):同 model 同 prompt,
  PATH 有無 ccodegraph 各跑 N=3,讀實際計費 token——這才是產品數字。
- **SKILL 觸發測試**:10 個問題描述,LLM 能選對動詞與旗標(含一題需要
  `--ambiguous`、一題需要判讀 semantic:absent)。
- 每動詞 golden stdout + golden JSON(codex R2 測試缺口 T5)。

## 6. 交付順序

1. `explore` 動詞 + 全動詞 `--json`(程式)
2. SKILL.md(含風險判讀章)+ golden 測試
3. 真 LLM A/B → 數字進 README/研究附錄
4. codex 第三輪 review(NFR6):審 SKILL.md 是否「LLM 只讀它就會用」
