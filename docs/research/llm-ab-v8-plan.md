# v8 計畫:慢 build 編輯對決——make 迴路變貴之後,diagnostics 的時間價值(2026-07-20 二稿,未開工)

> **研究問題**:v7 證明「diagnostics = make」——前提之一是 make
> **秒級**。大型專案/monorepo/CI 環境的 make 是分鐘級甚至更久,此時
> agent 每驗證一次都要付真實代價:毫秒級 diagnostics 的時間價值
> 終於有了兌換空間。v8 把 v7 的戰場原封不動搬進「每次 make 都很貴」
> 的世界,量測:agent 的行為如何適應?diagnostics 省下多少?正確性
> 有沒有因為「捨不得驗證」而掉?
>
> **使用者定案(2026-07-20,取代一稿的殘缺樹設計)**:模擬「可以
> build 但 build 很久」——改 Makefile 強制每次 make 都 full clean
> rebuild。一稿(刪 build 系統)存檔於 git 歷史,留作未來變體。

## 拍板記錄

①慢 build 模擬 = **wrapper Makefile 強制 clean rebuild**;②題目全
重用 v7 的 8 題;③四臂照 v7(none/lsp-on/lsp-off/ccodegraph)。

## 1. 慢 build 機制(agent 側)

原 `Makefile` 改名 `Makefile.real`,同位置放 wrapper:

```makefile
%:
	@$(MAKE) -f Makefile.real clean >/dev/null 2>&1 || true
	@sleep $(V8_DELAY)
	@$(MAKE) -f Makefile.real $@
```

- 任何 make 目標(含單檔 .o)都過 wrapper → 強制 clean + 延遲 +
  全量重建,**單目標繞道無效**。
- 實測 clean rebuild:redis 21s(make clean 不清 deps)、wpa 3s——
  都不足以構成決策壓力。**校準延遲至每次 make ≈ 120s**(redis
  sleep ~100、wpa sleep ~117),明標為人工模擬(模擬 kernel/
  monorepo 級 build 成本;校準值寫死並歸檔)。
- v7 基線:agent 每 run 跑 ~3 次 make → v8 中照跑 = 6 分鐘純等待。
  行為適應(少跑 make?改用 clangd?裸推理直接交卷?)是量測目標。
- agent 可手動 `gcc -fsyntax-only` 單檔(自建快迴路的辛苦路,-I 要
  自己湊;其成本如實記錄)。

Prompt 附註(四臂同文):「此專案 build 較慢:每次 make 都會強制
全量重建,約需 2 分鐘。請自行權衡驗證策略。」——誠實告知,不禁止
任何路線;決策本身是實驗對象。

## 2. 四臂(照 v7;殘註不變)

none / lsp-on(clangd + hook 診斷,v7 bear DB 路徑重寫)/ lsp-off
(nodiag 變體,隔離診斷淨價值)/ ccodegraph(零 compile DB 合成)。
**慢 build 世界的理論排序**:lsp-on 的毫秒診斷應最大化省 make;
ccodegraph 的枚舉可省「用 make 找站點」;none 只能付錢或裸奔。

## 3. 判分(v7 verify 全重用,零改造)

樹可 build(只是慢)→ verify 直接在 agent 樹跑,唯一前置:裁判先
把 `Makefile.real` 還原為 `Makefile`(拆 wrapper),verify 內的
make 不付人工延遲。PASS/FAIL 標準與 v7 逐字相同 → 跨輪對照乾淨。

## 4. 指標(鑑別重心從 PASS 轉向效率×正確性的交換)

主:PASS 率(若 agent 捨不得驗證 → 正確性掉,是核心假設之一)。
效率:wall(含等待)、**make 呼叫次數**(v7 基線 ~3/run)、成本。
行為:transcript 統計 make/gcc/clangd(hook 注入)/LSP 呼叫的組成
變化 vs v7——同題同臂,唯一差異是 make 價格,**行為差 = 價格效應**。

## 5. Phase 0 閘門

1. wrapper 在兩 repo 正常工作(make 任意目標 → clean+delay+rebuild;
   計時 ≈120s);verify 拆 wrapper 後結果與 v7 基線一致。
2. hook(clangd --check)不受 wrapper 影響(它不走 make)。
3. ccodegraph 建圖不受影響(不用 make)。
4. smoke 1 題 × 4 臂:確認 agent 真的感知到 make 代價(transcript
   可見等待/決策)且 timeout 3600s 足夠。

## 6. 規模/成本/時程

96 runs(8×4×3);wall 變長(等待不耗 token,budget $4 不變;
timeout 上調 3600s);估 $55-90、全量 12-20h elapsed(等待墊高)、
共 ~2 天。smoke 後凍結 checkpoint 照例。

## 7. 預期結果三讀法(先寫死)

1. **lsp-on 省 make 且保正確**(make 次數 <1/run、wall 最短、PASS
   全):diagnostics 的時間價值實錘,「慢 build 環境請開 LSP」寫進
   價值地圖——v6/v7/v8 構成完整的成立條件邊界。
2. **agent 少驗證 → 正確性掉,且各臂掉幅不同**:none 掉最多(無
   替代迴路)、lsp-on 掉最少 → 同樣支持主張,且多了「正確性保險」
   維度。
3. **全臂仍全 PASS 且 make 照跑 ~3 次**:agent 對時間成本不敏感
   (batch 模式沒有不耐煩),人工延遲只是統一加稅——設計失效的
   誠實記錄,結論轉向「時間價值需要互動場景(人在等)才兌現」。

## 8. 風險

| 風險 | 處置 |
|---|---|
| agent 對延遲無感(讀法 3) | 本身就是發現;prompt 已明告 build 貴,決策仍歸 agent |
| sleep 模擬被質疑不真實 | 明標校準值與理由;redis 21s 真實部分保留;未來變體可上真 kernel |
| gcc -fsyntax-only 旁路太好用 | 如實記錄(它就是「手動 LSP」,-I 湊齊的成本是真實摩擦) |
| timeout/等待墊高成本 | timeout 3600s;等待不耗 token,錢不變、時間變長 |
