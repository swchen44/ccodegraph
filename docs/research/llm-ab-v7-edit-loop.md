# LLM A/B v7:編輯迴路對決——LSP diagnostics 的主場實測(2026-07-20)

> **TL;DR**:外部證據說 LSP 的真主場是編輯迴路(改碼後毫秒級
> diagnostics)。受控實測(8 個編輯任務 × 4 臂 × N=3 = 96 runs,
> **編譯器機械判分**):**四臂全部 24/24 PASS,完美打平**——包括
> 37 站點跨 10 檔的 API 遷移與 17 站點抽結構。diagnostics on/off
> 零差異的機制在 transcript 裡:**agent 的天然工作流(grep→Edit→
> `make` 驗證)自帶完備的診斷迴路**——四臂都每 run 跑 ~3 次 make,
> 毫秒級推送對抗的從來不是「無回饋」,而是「agent 自己跑 make」,
> 在中型 C repo 秒級 build 下毫無增值空間;hook 推送反而讓 lsp-on
> 臂最慢(+32% wall)。LSP 查詢工具在編輯任務**幾乎零使用**
> (96 runs 共 5 次呼叫)——比 v6 導航的 36% 零使用更極端。
> ccodegraph 在域外誠實記錄:+29% 成本、+37% turns、零正確性增益。
> **編輯任務對 2026 年的 sonnet 已全面飽和**:「找齊站點+改對+
> build 過」不再是鑑別性挑戰;要拉開差距需要 build-pass 之外的
> 維度(語意正確性、測試通過、更大 repo)。

## 名詞對照

同系列術語表見 README 或 `llm-ab-v6-lsp.md` 開頭(arm/GT/oracle/
雙閘控/spike/DNF/零回歸/wall/N=3/smoke/幻影/同場/凍結/headless/turns)。

## 1. 背景與設計

v6 適用域聲明留下的未測戰場:編輯迴路(`lsp-external-evidence.md`
的外部主張 A 類)。設計全記錄於 `llm-ab-v7-plan.md`(含使用者拍板
的四個決策與兩次修訂);Phase 0/1/2 工程記錄同文件與
`v7-analysis/phase1-notes.md`。要點:

- **四臂**:none / lsp-on(clangd plugin + PostToolUse hook 診斷,
  Phase 0 驗證的可靠通道)/ lsp-off(nodiag plugin 變體,隔離
  diagnostics 淨貢獻)/ ccodegraph(零 compile DB 合成模式——
  「路線對決」:lsp 臂用 bear 真實 DB 是其路線前提,ccodegraph 的
  主張是不需要它)。
- **8 題四族**(`v7/questions-v7.jsonl`,GT 由參考編輯的編譯器點名):
  型別傳播(ET-001 易 3 站點/ET-002 難 10 站點 9 檔)、注入錯
  (ET-003 易 2 錯/ET-004 難 5 錯 5 檔)、抽結構(ET-005 易 12 站點/
  ET-006 難 17 站點 7 檔)、API 遷移(ET-007 易單檔/ET-008 難
  37 站點 10 檔)。
- **裁判 = 編譯器**:`verify_ET-00X.sh` 機械判分(make -k 零 error +
  站點/token 檢查),零評分成本、零評分者偏誤。smoke 期抓到並修復
  詞界 bug(子串誤匹配)——裁判要先驗的第五課。
- 條件:sonnet-5、budget $4、timeout 2400s、每 run 全新樹、循序、
  N=3;prompt smoke 後凍結(附錄 A)。

## 2. 結果:主指標完全飽和

| 臂 | PASS | 總成本 | wall 中位 | turns 中位 |
|---|---|---|---|---|
| none | **24/24** | $12.97 | 88s | 16 |
| lsp-on | **24/24** | $12.72 | **120s** | 16 |
| lsp-off | **24/24** | $11.94 | 91s | 15 |
| ccodegraph | **24/24** | **$16.72** | 99s | **22** |

96/96 全 PASS(逐題矩陣全 3/3),零 harness 失敗,總成本 $54.35。
**8 題全部無鑑別度**——包括預設「失敗率高是設計目標」的難題。

## 3. 為什麼 diagnostics 沒有價值空間(transcript 機制分析)

| 臂 | Edit/Write | hook 診斷注入* | LSP 呼叫 | 用 LSP 的 runs | make 呼叫 |
|---|---|---|---|---|---|
| none | 90 | — | 0 | 0 | 65 |
| lsp-on | 105 | ~92 行 | 4 | 2 | 70 |
| lsp-off | 99 | — | 1 | 1 | 68 |
| ccodegraph | 126 | — | 0 | 0 | 77 |

(*行級計數含 agent 引用,為上界;通道活躍性已由 Phase 0/2 端到端驗證。)

三個機制發現:

1. **make 是所有臂的通用診斷迴路**:每 run ~3 次。agent 改完就跑
   make、看錯誤、再改——這是它的肌肉記憶,而中型 C repo 的增量
   build 是秒級。diagnostics 推送提供的「毫秒 vs 秒」在批次任務中
   毫無意義;它對抗的不是「無回饋」而是「稍慢的回饋」。
2. **hook 推送是純開銷**:lsp-on 每次 Edit 觸發 clangd --check
   (1-3s),wall 120s vs lsp-off 91s(+32%),正確率零差。
3. **LSP 查詢工具在編輯任務近乎絕跡**:96 runs 共 5 次呼叫
   (v6 導航還有 117 次)。編輯任務的定位需求(找呼叫點)被
   「編譯器點名」取代——agent 直接改簽名、跑 make、讓 error 清單
   告訴它哪裡要改。**編譯器就是最好的 findReferences**,這正是
   我們 Phase 1 建 GT 用的同一招。

## 4. ccodegraph 域外誠實記錄

+29% 成本、+37% turns、edits 最多(126)、正確性零增益。建圖
(~3-4s)是小頭;大頭是 agent 查圖的 turns 在編輯工作流中是**替代
不了 make 的繞路**——它查 callers 得到站點清單,但 make 的 error
清單同樣給站點還附帶「哪裡型別不合」。編輯任務不是圖工具的戰場,
與 v6 導航的 +3 形成清晰的域界。

## 4.5 難度梯度分析(飽和之下僅存的訊號)

按易/難分層的成本曲線(wall 中位數):

| 臂 | 易題 | 難題 | 難/易倍率 |
|---|---|---|---|
| none | 66s | 113s | **1.71x** |
| lsp-on | 90s | 130s | 1.45x |
| lsp-off | 75s | 101s | **1.36x** |
| ccodegraph | 85s | 115s | **1.36x** |

**工具臂的斜率確實比 none 平**(1.36-1.45x vs 1.71x)——難度上升時
工具的固定開銷開始攤提,這與「工具價值隨規模成長」的假設方向一致。
但兩個限定:①v7 難度範圍內曲線**未交叉**(none 難題 113s 仍快於
lsp-on 難題 130s);②正確性全程無差(37 站點題四臂仍 100%)。外推
「更難就會贏」缺乏依據——因為站點數不是正確的難度軸(見 §5.2):
只要 make 迴路完備,站點再多也只是機械工作量,編譯器都會點名。

## 5. 誠實結論

1. **外部「LSP 編輯迴路」主張在本設定下不成立**:diagnostics
   on/off/none 三態零差異(96 runs 受控)。適用域:C × 中型 repo ×
   agent 可自由跑 make × 任務有明確 build 判準。**不可外推**到:
   build 要 30 分鐘的 monorepo(make 迴路變貴,推送價值上升)、
   無法 build 的殘缺樹、TS/Java(ManoMano 的 Java 重構中內建 LSP
   仍留 9 個測試失敗——但 Serena 過了,說明大 repo 重構有真差距)、
   IDE 互動場景(人在等,毫秒有感)。
2. **編輯任務已飽和**:2026 年的 sonnet 對「找齊站點+改對+build 過」
   類任務 100% 完成,37 站點跨 10 檔也不例外。v7 若有續集,鑑別
   維度必須升級:語意正確性(build 過但邏輯錯)、測試通過(本輪
   驗收只 make,redis 測試套件未納入——已知限制)、超大 repo
   (kernel 級編輯)、或殘缺環境(不能 build 時 diagnostics 才是
   唯一迴路)。
3. **方法論收穫**:編譯器機械判分完美運作(96 判分零成本零偏誤,
   對照 v3-v6 的 codex 評分),smoke 抓到詞界 bug 是第五次「裁判
   先驗」教訓;「參考編輯收編譯器點名」的 GT 建構法可複用。
4. **系列弧線收攏**:v6(導航)LSP=grep;v7(編輯)diagnostics=
   make。兩輪合起來的可轉移結論:**agent 的 shell 肌肉記憶(grep+
   make)在中型 C repo 上是一條完備的工作流**,結構化工具的增值
   空間只存在於這條工作流覆蓋不到的地方——超大規模(v5 索引)、
   無法 build 的環境、以及需要跨 config 枚舉的問題(v3/v6 的
   雙閘控/includes)。工具定位應該瞄準工作流的縫隙,而不是與
   肌肉記憶正面競爭。

## 6. 限制

- 驗收未含測試套件(僅 build);語意錯誤(build 過邏輯錯)未偵測
  ——飽和結論部分源於此判準天花板。
- hook 通道是模擬(原生推送間歇,Phase 0 記錄);「diagnostics 無
  價值」的結論對原生毫秒級通道同樣成立(hook 比原生更保證送達)。
- 單模型單日期窗;lsp-on 的 hook 開銷數字依 clangd --check 延遲
  (本機 1-3s)而定。
- ccodegraph 臂用 SKILL 但其教學面向導航問答,無編輯任務章——
  域外測試的公平性以「工具原樣」為準。

## 附錄 A:四臂 prompt(smoke 後凍結)

見 `v7-analysis/run_v7_edit.py` 的 TPL_NONE/TPL_LSP/TPL_CCG
(lsp-on/lsp-off 共用 TPL_LSP,單變因)。任務原文:
`v7/questions-v7.jsonl`;GT 與驗收:`v7/gt_ET-*.md` + `v7/verify/`;
原始 runs:`v7-runs/`(96 份 JSON + summary 含逐 run verdict)。
