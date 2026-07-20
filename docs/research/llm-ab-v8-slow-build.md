# LLM A/B v8:慢 build 編輯對決——make 變貴之後,agent 選擇不驗證,而且沒事(2026-07-20)

> **TL;DR**:v7 說「diagnostics = make」;v8 把每次 make 的價格提到
> ~60 秒(wrapper 強制全量重建,使用者定案校準),量 diagnostics 的
> 時間價值會不會兌現。結果:**96/96 全 PASS 四臂又死平**,但行為
> 數據劇烈——agent 對價格高度敏感,**全量 rebuild 從 v7 的 ~3 次/run
> 砍到 ~0.4-0.6 次/run(-83%)**;而它的適應方式**不是**換更快的
> 驗證通道(gcc 手動迴路 0 次、LSP 2 次、lsp-on 的 hook 注入 100 行
> 沒兌換任何優勢),而是**乾脆不驗證、裸交卷——而且裸交卷全對**。
> 預寫三讀法的第 3 種成立且加強:對 2026 年的 sonnet,在中型 C repo
> 的編輯任務上,**驗證迴路本身是可選的奢侈品**——貴了就不用,
> 不用也不錯。LSP 價值主張三連敗:導航=grep(v6)、編輯=make(v7)、
> 慢 build=不驗證(v8)。

## 名詞對照

同系列術語表見 README 或 `llm-ab-v6-lsp.md` 開頭。

## 1. 設計(全記錄於 `llm-ab-v8-plan.md` 二稿)

- **慢 build 機制**:wrapper Makefile(redis 包 `src/Makefile`、wpa 包
  `wpa_supplicant/Makefile`)——任何 make 目標(含單檔 `.o`、既存檔)
  一律強制 clean + 校準延遲 + 全量重建,每次 ≈60s(使用者定案;
  redis delay 25 + 真實 rebuild ~34s、wpa delay 50 + ~10s)。
  Wrapper 硬化史(四個 GNU make 陷阱:match-anything 不重建既存檔/
  內建隱式規則搶先/**Makefile remaking 雙重計費**/遞迴重入)全靠
  計時證據抓出,詳 commit 記錄——工程上這是本輪最痛的部分。
- **prompt 誠實告知**(四臂同文):「每次 make 強制全量重建約 1
  分鐘,請自行權衡驗證策略」——不禁止任何路線,決策是實驗對象。
- 題目/臂/裁判:v7 全套重用(8 題四族、四臂、verify 腳本;裁判先
  拆 wrapper 再判)。同題同臂同裁判,**唯一差異是 make 價格**——
  行為差 = 純價格效應。
- 條件:sonnet-5、budget $4、timeout 3600s、每 run 新樹、N=3。

## 2. 結果

| 臂 | PASS | 成本 | wall 中位 | turns 中位 |
|---|---|---|---|---|
| none | **24/24** | $11.50 | 155s | 16 |
| lsp-on | **24/24** | $12.19 | 162s | 16 |
| lsp-off | **24/24** | $10.54 | **144s** | **12** |
| ccodegraph | **24/24** | $12.48 | 182s | 17 |

96/96 零 harness 失敗、零 FAIL,總成本 $46.72。正確性再次完全飽和。

## 3. 價格效應(本輪核心數據)

| 臂 | 全量 rebuild 觸發(24 runs) | 每 run | v7 基線 | gcc 手動 | LSP | hook 注入 |
|---|---|---|---|---|---|---|
| none | 9 | 0.38 | ~3 | 0 | 0 | — |
| lsp-on | 14 | 0.58 | ~3 | 0 | 1 | ~100 行 |
| lsp-off | 11 | 0.46 | ~3 | 0 | 1 | — |
| ccodegraph | 10 | 0.42 | ~3 | 0 | 0 | — |

三個發現:

1. **價格彈性極高**:make 從免費變 60s,使用量 -83%~-87%。Agent
   讀了 prompt 的價格告知並真的改變行為——batch agent 並非對時間
   無感(預寫讀法 3 的「無感」半句被推翻)。
2. **適應方向是「不驗證」而非「換通道」**:沒有任何 run 用
   `gcc -fsyntax-only` 自建快迴路;LSP 查詢兩輪合計 2 次;lsp-on 的
   hook 每次編輯照常注入(~100 行診斷)卻沒有兌換出任何 PASS 或
   速度優勢(它反而比 lsp-off 慢 12%——注入的 clangd --check 延遲)。
   **面對貴的驗證,agent 的答案是信任自己的編輯。**
3. **而信任是對的**:四臂在大幅削減驗證後仍 96/96 全對——說明
   v7 裡那 ~3 次 make 對這些任務本來就是**冗餘保險**,不是正確性
   的必要條件。v7 的「diagnostics=make」在 v8 退化為更強的陳述:
   「**這個難度等級的編輯任務,驗證迴路整個是可選項**」。

## 4. 三輪合訂:LSP-for-agents 價值主張的完整檢驗

| 輪 | 場景 | 外部主張 | 受控結果 |
|---|---|---|---|
| v6 | 唯讀導航 | 語意查詢勝文字搜尋 | LSP = grep(60=60);教學層 +1 |
| v7 | 編輯(make 免費) | 毫秒診斷勝 build 迴路 | diagnostics = make(四臂全 PASS)|
| v8 | 編輯(make ~60s) | 診斷的時間價值兌現 | **agent 直接不驗證,仍全對** |

合訂結論:在 *C × 中型 repo × 2026 模型* 的條件下,LSP 對 agent 的
三個理論價值(語意導航、即時診斷、省驗證時間)**全部沒有可量測的
兌現**——不是因為 LSP 弱,而是因為 (a) grep+make 工作流完備
(v6/v7),(b) 模型的編輯正確率已高到驗證本身冗餘(v8)。結構化
工具的殘存價值空間收斂到:超大規模索引(v5)、跨 config 枚舉
(雙閘控/includes)、以及本系列未測的域(TS/Java 大 repo、真
kernel 級 build、無法 build 的樹、互動場景)。

## 5. 限制

- 任務集與 v7 相同,已知飽和;「裸交卷全對」**不可外推**到更難的
  任務(語意錯誤/測試級判準)或更大的 repo——那裡削減驗證可能
  真的付出代價,而各臂的安全網差異才會現形。
- 60s 是模擬校準(真實成分:redis ~34s rebuild);真 monorepo 的
  30 分鐘 build 或許把行為推向不同的均衡(如認真轉向 per-TU 工具)。
- 每次 make 全量重建比真實增量 build 嚴苛;真實世界 agent 可能用
  增量 make 得到更便宜的迴路。
- 單模型單日期窗;batch 模式(無人等待)的時間壓力與互動場景不同。

## 附錄

Prompt/題目/GT/verify:v7 資產(`v7/`、`v7-analysis/`);wrapper
模板與 harness:`v8-analysis/`(make-wrapper.tmpl、run_v8_slow.py);
原始 runs:`v8-runs/`(96 JSON + summary 含逐 run verdict)。
