# v7 計畫:編輯迴路對決——LSP diagnostics 的主場實測(2026-07-19 定稿,未開工)

> **研究問題**:外部證據(`lsp-external-evidence.md`)說 LSP 的真主場是
> **編輯迴路**(改碼後毫秒級 diagnostics)。v6 只測了唯讀導航;這輪受控
> 驗證:diagnostics 通道對 agent **改 C 碼**的正確性值幾分?ccodegraph
> 在自己域外(無 diagnostics)站在哪?
>
> **方法論紅利**:裁判從 codex 換成**編譯器**——build 過/測試過/站點
> 改齊全是機械二值,比 0-3 評分乾淨一個等級。

## 使用者已拍板(2026-07-19)

四臂(含 diag-off 隔離臂)/ 8 題全套 N=3 / 混合難度梯度 / 專注 C(TS 留 v8)。

## 1. 四臂設計

| 臂 | 工具 | 差異點 |
|---|---|---|
| none | grep/read/edit + 可自跑 `make` | 基線 |
| **lsp-on** | + clangd plugin(`diagnostics: true`) | **受測通道:編輯後自動推錯誤進 context** |
| **lsp-off** | + clangd plugin(`diagnostics: false`) | 導航能力同上、無自動診斷——**隔離 diagnostics 的淨貢獻** |
| ccodegraph | + 圖工具(SKILL) | 域外誠實測;呼叫點枚舉理論上幫「改齊」 |

lsp-on vs lsp-off 的差 = diagnostics 淨值;lsp-off vs none 的差 = LSP 導航在編輯任務的殘值。
四臂都能自跑 make(真實條件);prompt 比照 v6 待遇原則,smoke 後凍結。

## 2. 題目(8 題,四族 × 一易一難;wpa/redis 各 4)

| 族 | 易(呼叫點 <5、≤2 檔) | 難(≥10 站點、跨 ≥3 檔) | 機械驗收 |
|---|---|---|---|
| 改簽名 | redis:小工具函式加參數 | wpa:熱門 util 函式加參數(呼叫點 10+) | build 過 + GT 站點全改(殘留舊簽名 grep=0) |
| 抽結構 | wpa:小 struct 抽 2 欄位 | redis:熱門 struct 抽欄位群(ManoMano 式) | build 過 + 測試過 |
| 修注入錯 | redis:注入 2 個型別誤用 | wpa:注入 5 個(跨檔、含漏 include) | build 過 + 注入清單全中(patch 可重現) |
| API 遷移 | wpa:低頻 API 換名 | redis:高頻 API 換名+參數順序變 | build 過 + 殘留舊呼叫 grep=0 |

選題原則:呼叫點數用圖+grep 雙法預數(GT);注入錯誤以 patch 檔固定
(可重現);難題失敗率高是**設計目標**(v6 飽和教訓——要的就是能拉開
差距的區間)。

## 3. 指標

**主指標(機械,免 codex)**:①build 通過率 ②測試通過率(redis 套件;
wpa 以 build 為主)③站點覆蓋率(GT 站點清單 vs 實改;漏改數)④注入錯
命中率。
**次指標**:turns/成本/wall;diagnostics 推送次數與 agent 反應
(transcript);agent 自跑 make 次數(lsp-on 臂理論上更少——診斷替代了
build 輪);「改壞再改回」次數。
**加分分析**:失敗案例逐 transcript 歸因(找不齊站點?改壞沒發現?
診斷有推但沒讀?)。

## 4. 執行協定(沿用 v6 全套)

隔離乾淨樹(每 run 新樹——編輯任務污染樹,不能共用)、
`--setting-sources project`、frozen prompts、循序、N=3、resume key
(qid, arm, rep)、timeout 上調 2400s(含 build 時間)、
`--max-budget-usd 4`。8 × 4 × 3 = **96 runs**。

## 5. Phase 0 閘門(開工後最先驗,兩個都可能斃掉整案)

1. **可編譯性**:乾淨樹的 wpa(v2/v3 build config)與 redis 在本機
   `make` 全綠;注入 patch 後 make 如預期失敗。
2. **headless 下 diagnostics 推送真的發生**:v6 只驗了 LSP 查詢工具,
   沒驗「Edit 後自動推診斷」在 `claude -p` 是否工作;smoke 1 題看
   transcript 有無 diagnostics 注入。不工作 → 停下回報選備援
   (如 hook 包 make 模擬推送 vs 改實驗問題)。

## 6. 時程與預算

| 階段 | 內容 | 估計 |
|---|---|---|
| Phase 0 | 兩個閘門 | 0.5 天 |
| Phase 1 | 8 題出題 + GT(站點清單/patch)+ 驗收腳本 | 1 天 |
| Phase 2 | smoke(2 題 × 4 臂)→ prompt 凍結(使用者 checkpoint) | 0.5 天 |
| Phase 3 | 全量 96 runs | ~8-14h elapsed,$70-120 |
| Phase 4 | 機械判分 + transcript 分析 + 報告 `llm-ab-v7-edit-loop.md` | 1 天 |

## 7. 預期結果的三種讀法(先寫好,防事後諸葛)

- **lsp-on 顯著贏 lsp-off**:diagnostics 淨值實錘——外部主張被受控
  證實;ccodegraph 域外弱勢如實記錄,「編輯迴路請用 LSP」寫進定位。
- **lsp-on ≈ lsp-off ≈ none**:編輯迴路主張在 C 中型 repo 也不成立
  ——比 v6 更強的負結果(直接打外部證據的核心主張),投放價值極高。
- **ccodegraph 在「改齊站點」題型追平 LSP**:枚舉原語在編輯任務也值錢
  ——域外不弱,定位擴張的證據。

## 8. 風險

| 風險 | 處置 |
|---|---|
| headless 無 diagnostics 推送 | Phase 0 閘門,備援方案回報使用者 |
| wpa 在 macOS build 不穩 | 已有 v2/v3 的可行 config;不穩則題目向 redis 傾斜並記錄 |
| 編輯任務 run 間變異大 | N=3 中位 + 難易分層分析;必要時 checkpoint 加 rep |
| 每 run 新樹 + build 讓 prep 變慢 | prep 計時單列,不混入 agent 計時 |
