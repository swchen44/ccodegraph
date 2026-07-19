# 投放包(A1:收 ≥10 條外部反饋)

v5 §12.2 凍結令的指定動作:用外部訊號而非第七輪內部 benchmark 決定
v6 之後的方向。**發文動作由使用者本人執行**;本資料夾是可直接貼的
成稿 + 策略。

## 素材 × 平台矩陣

| 稿件 | 平台 | 主素材 | 風險/信譽 |
|---|---|---|---|
| `cscope-upstream-issue.md` | cscope 專案(SourceForge tracker) | cscope 查詢引擎三類 bug + 最小重現 | **已投放(2026-07-19):https://sourceforge.net/p/cscope/bugs/306/** |
| `reddit-claudecode.md` | r/ClaudeCode(v6 的靈感來源社群) | v6 LSP 對決 + 「裝了不用」的量化 | 直接回應社群自己的熱門話題,最可能有高質量反饋 |
| `reddit-cprogramming.md` | r/C_Programming | cscope bugs + no-build C 索引器 | C 工具人群,對 cscope 議題有感 |
| `hn.md` | Hacker News | v6 誠實負結果 + 可重現包 | 曝光最大、批評最狠;放最後,吸收前面反饋再發 |
| `lobsters.md` | lobste.rs(tags: ai, c, testing) | 同 HN,較技術向 | 社群小而精,對方法論友善 |

## 建議順序

1. **cscope issue**(先發——之後所有貼文都能連結它,證明「我們回饋 upstream」)
2. **r/ClaudeCode**(最對口的受眾;那裡就是 v6 的起點)
3. 隔 2-3 天:**r/C_Programming**
4. 吸收修正後:**HN + lobste.rs**(同日)

## 要收集的反饋(貼文末尾的提問,對應決策)

1. 你在什麼場景需要「不用 build 就能查 C 大專案」?(→ 定位驗證)
2. 巨集/多 config(`#ifdef`)的導航痛點,現有工具解決了嗎?(→ 護城河驗證)
3. 你的 LSP-for-agents 成功案例是什麼任務/語言/規模?(→ v6 適用域驗證)
4. kernel 級(50k+ 檔)的圖,你要的是什麼查詢?(→ B1 歧義爆炸要不要修)
5. 如果只能拿走一樣:工具、教學層(SKILL)、還是 benchmark 方法論?(→ 資產排序驗證)

## 紅線

- 所有數字必須可追溯到 repo 內文件;不確定的說不確定。
- 負結果照登(LSP=grep、教學層只 +1、題庫飽和)——這是信譽來源,不是弱點。
- 不承諾 roadmap;收反饋是目的,不是行銷。
