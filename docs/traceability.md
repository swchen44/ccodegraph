# FR/NFR 追溯矩陣(codex R2 缺口 T1;每需求 → 驗證所在)

| 需求 | 驗證 | 所在 |
|---|---|---|
| FR1 schema 合約 | Schema Contract §1.5(enum 全列)+ integration 全套讀寫 | design.md §1.5;tests/integration |
| FR2 分層填料/可重跑 | clink 層重跑無重複(test_rerunnable);增量只動受影響 origin | test_build.py:TestClinkImport / TestIncremental |
| FR3 fnptr 人工表 | registrations/links/壞 JSON/STALE 四向 | TestLoadManual(unit)+ test_manual_*(int)+ test_manual_stale_warning(e2e) |
| FR4 消歧 D1 | static 同檔/header 例外/非 static 掛靠/同檔 #ifdef/行區間歸戶 | TestChooseDst、TestAttributeSrc、TestAssignQnames(unit)+ fixture 逐案(int) |
| FR5 查詢動詞 | 各動詞 e2e golden 斷言;--min-conf 進 SQL;D4 impact 預設排 ambiguous | test_cli.py 全套 |
| FR6 產物集中 | .ccodegraph/ 路徑 + 自動 .gitignore(建圖時寫入) | build();e2e 建圖路徑斷言(隱含);**待補顯式 e2e(backlog)** |
| FR7 git 增量 | up-to-date 早退/新邊/保留邊/刪檔/normalized diff=0 | TestIncremental(int)+ wpa 真機(design §9 L5 行) |
| FR8 查詢層 for LLM | SKILL 觸發實測(codex 第三輪 10 題)+ 真 LLM A/B | docs/reviews/…round3 + docs/research/llm-ab.md |
| FR9 --json 雙軌 | JSON 欄位與文字一致斷言 | test_json_*(e2e) |
| NFR1 標準庫 only | import 面檢查(人工)+ 退化訊息測試 | —(靠 code review;無自動閘,已知) |
| NFR2 輕量快 | wpa 90s/3.9s 實測 | design §9 數字 |
| NFR3 ctags 相容 | flavor 分類 4 案 + CI 三平台 | TestClassifyCtags + ci.yml |
| NFR4 三層測試 | 115+ tests,commit 全綠 | git log 慣例 |
| NFR5 決策記錄 | D1–D13 + 三輪 review 歸檔 | design.md §8.x、docs/reviews/ |
| NFR6 定期紅隊 | 三輪已跑,處置全記錄 | docs/reviews/ ×3 |
