# v8 計畫:殘缺樹編輯對決——make 迴路死亡之後,誰還活著(2026-07-20 定稿,未開工)

> **研究問題**:v7 證明「diagnostics = make」——前提是 make 能跑。
> 真實世界的 C 樹經常不能(原始碼快照無 build 系統、缺 vendored
> 依賴、交叉編譯、老碼配新編譯器)。在 make 迴路死亡的樹上:
> clangd 的 per-TU 診斷(不需全樹可連結)與 ccodegraph 的 no-build
> 圖(zero-build 定位的原生主張)**主場對主場**——這次沒有 make
> 當外掛裁判,誰真的有用一翻兩瞪眼。
>
> **設計靈魂:資訊不對稱**——agent 只看得到殘缺樹;裁判把 agent 的
> 編輯 diff 搬回完整樹,用 v7 的 verify 全套(make + 站點檢查)判分。

## 使用者拍板(2026-07-20)

①殘缺方式 = **刪 build 系統**(「用 clean build」解讀為:乾淨的
原始碼快照、無 build 可用——模擬拿到 tarball 沒有 Makefile/
configure 的常見情境;若解讀有誤以使用者更正為準);
②題目 = **全重用 v7 的 8 題**(GT/驗收/參考數字重用,白送「同題
可 build vs 不可 build」跨輪對照);③**四臂照 v7**(none/lsp-on/
lsp-off/ccodegraph,保留 diagnostics 淨價值隔離——殘樹上這個差異
才真正有機會顯現)。

## 1. 殘缺樹製造(agent 側)

從 v7 同一 commit 的乾淨樹出發,移除:
- redis:`Makefile`、`src/Makefile`、`deps/Makefile`、`configure*`、
  `*.mk`(保留全部 .c/.h)
- wpa:`wpa_supplicant/Makefile`、`src/**/Makefile`、`.config` 不種

Prompt 附殘缺聲明:「這棵樹是原始碼快照,**沒有 build 系統,
make 無法使用**;不要嘗試重建 build 系統或下載任何東西,直接完成
以下編輯任務。」(agent 仍可手動 `gcc -fsyntax-only` 單檔——那是
「手動重建診斷迴路」的辛苦路,其成本正是實驗要量的東西之一。)

## 2. 四臂條件

| 臂 | 殘樹上還有什麼 | 預測 |
|---|---|---|
| none | 裸 grep/Read/Edit,無任何驗證迴路(除非手動 gcc) | 漏站點/改壞不自知 → 掉分 |
| lsp-on | clangd per-TU 診斷(v7 的 bear DB 重用——樹同 commit,路徑重寫;+hook)+ 查詢 | 理論最大受益者:唯一的自動「改壞了沒」訊號 |
| lsp-off | 只有 LSP 查詢,無診斷 | 隔離:查詢 vs 診斷誰在殘樹值錢 |
| ccodegraph | no-build 圖(callers/refs 枚舉)+ SKILL | 主場主張:枚舉補「make 點名」的死亡 |

注:lsp 臂的 compile DB 用 v7 的 bear 產物(當時樹可 build 收的)
——語意:「這專案曾經 build 過、DB 是歷史遺產」,真實情境常見;
DB 內的路徑重寫到殘樹。**此設計讓 clangd 拿到高品質 DB,是對 LSP
最有利的設定**(誠實標注;若它這樣還不贏,主張徹底終結)。

## 3. 判分(裁判側,v7 資產全重用)

1. run 結束後 `git diff`?否——殘樹非 git repo。改為:記錄 agent 樹
   與殘缺基準樹的檔案差集(`diff -ruN baseline/ agent/` 產 patch)。
2. 把 patch 應用到**完整樹**(有 build 系統的 v7 gate 樹複本)。
3. 跑 v7 的 `verify_ET-00X.sh`(make -k + 站點/token 檢查)照舊判
   PASS/FAIL。
4. patch 應用失敗(agent 改了被刪的 build 檔等)→ FAIL 記原因。

## 4. Phase 0 閘門(開工先驗)

1. **make 死透**:殘樹上 `make` 直接不存在目標;確認 agent 無法用
   殘存 mk 碎片繞回(掃殘樹無 *.mk/Makefile)。
2. **clangd 活**:殘樹 + 重寫 DB 下,`clangd --check` 對 8 題的目標
   檔基線雜訊夠低(注入錯能浮出);hook 通道同 v7 驗證。
3. **ccodegraph 活**:殘樹建圖正常(它本來就不需要 build 系統)。
4. **判分管線通**:對一個手工樣本(模擬 agent 編輯)走 diff→apply→
   verify 全鏈 PASS/FAIL 各一次。

## 5. 規模/成本/時程

96 runs(8×4×3)≈ $55-90;Phase 0+harness 改造 0.5 天、smoke
(2 題×4 臂)0.25 天含**凍結 checkpoint**、全量 8-14h、分析+報告
(`llm-ab-v8-broken-tree.md`)0.5 天。

## 6. 預期結果三讀法(先寫死)

1. **lsp-on 顯著贏 none(尤其贏 lsp-off)**:LSP 價值邊界找到——
   「不能 build 的樹」寫進其成立條件;v6/v7 的負結果與此構成完整
   價值地圖。
2. **ccodegraph 在改齊類(型別傳播/抽結構/API 遷移)追平或勝 LSP**:
   zero-build 枚舉的最強證據,直接支撐定位。
3. **全臂仍打平(裸推理就夠)**:兩家的殘樹主張同歸於盡——
   「2026 模型在中型 C repo 上連驗證迴路都不需要」,是三輪中最
   激進的負結果,投放價值最高。

## 7. 風險

| 風險 | 處置 |
|---|---|
| agent 手動 gcc 重建迴路太容易 → 殘缺無效 | 如實記錄(手動迴路的 turns/成本就是量測目標);gcc 路線的 -I 猜測成本天然高 |
| clangd 在殘樹的診斷雜訊 | Phase 0 閘門 2;必要時 DB 修剪 |
| diff→apply 判分管線的邊角(新檔/刪檔) | Phase 0 閘門 4 樣本演練 |
| 任務目標檔恰好依賴被刪的 build 生成物 | v7 題目標檔均為手寫源碼,無生成物依賴(已知) |
