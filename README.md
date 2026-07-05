# ccodegraph — C/C++ 知識圖譜(C 優先、多引擎、標注出處與信心)

給 LLM/agent 用的 C/C++ 程式碼知識圖:**零 build 需求**建圖(ctags + cscope +
啟發式),選配語意層(clink/libclang)與 git 層,全部填進同一個 SQLite——
每筆資料標 `origin` + `confidence` + 標籤,**判讀交給大模型,不確定的資料
被標注、不被刪除**。

- 需求(Why/What):[docs/requirement.md](docs/requirement.md) — 交接先讀這份
- 設計(How + 決策記錄 D1–D13):[docs/design.md](docs/design.md)
- 查詢層設計:[docs/query-layer-design.md](docs/query-layer-design.md)
- 研究筆記:[docs/research/](docs/research/)(clink 解剖、token spike、合成 DB A/B)
- 第三方紅隊審查(codex,三輪):[docs/reviews/](docs/reviews/)

## 快速開始

```bash
# 依賴:python3(標準庫)、universal-ctags、cscope;選配:clink
./ccodegraph.py build -p <repo>            # 零 build,~90s / 600 檔 → <repo>/.ccodegraph/graph.db
./ccodegraph.py clink-import -p <repo>     # 選配:語意層(自動偵測/合併/合成 compile DB)
./ccodegraph.py explore some_function -p <repo>    # 頭牌動詞:定義+callers+callees+全域讀寫,一發
./ccodegraph.py schema -p <repo>           # 第一動詞:格子、填充率、出處、STALE 警告
# 改碼之後:
./ccodegraph.py build --incremental -p <repo>      # 改 1 檔 ≈ 4s,與全量重建 diff = 0
```

所有查詢動詞支援 `--json`(欄位與文字一一對應,由 LLM 自選格式)。
所有中間產物集中在 `<repo>/.ccodegraph/`(自動 `.gitignore`,不污染你的空間)。

## 給 agent 安裝 skill(兩種方法)

```bash
# 方法一:內建輸出(內網/air-gapped 適用,零外部依賴)
mkdir -p ~/.claude/skills/ccodegraph
./ccodegraph.py skill > ~/.claude/skills/ccodegraph/SKILL.md

# 方法二:直接複製 repo 內的檔案
cp skills/ccodegraph/SKILL.md ~/.claude/skills/ccodegraph/SKILL.md
```

SKILL.md 的核心是**風險判讀章**:教 LLM 每一級 confidence「怎麼錯」、
`semantic:absent` 的 `#ifdef` 判讀、`ambiguous` 標籤與 `--ambiguous`、
STALE 處理——誠實標注只有在讀者會判讀時才有價值。

## 實測數字(wpa_supplicant 620 檔;方法見 docs/)

| 指標 | 數字 |
|---|---|
| 呼叫邊召回(cflow 28 邊 GT) | **28/28**(cscope 26、單一工具皆 ≤27) |
| fnptr `.scan2` 分派 | 5/5;callback 3/3 |
| 建圖 / 增量(改 1 檔)/ 無變更 | 90s / **3.9s** / 3.8s(增量與全量 normalized diff = 0) |
| 語意註記(clink) | confirmed 58k / absent 13.9k(= config-gated 碼的誠實訊號) |
| token(代理量測,8 任務) | 比 grep/Read 路徑省 **13×**(中位 44×);真 LLM A/B 見 docs |

## 依賴與退化

外部只依賴既有 binary(W5「整合不重寫」):**universal-ctags**(必要;
非 Universal 版會大聲死並給安裝指引)、**cscope**(必要)、clink(選配,
缺了明講跳過)、git(選配,缺了 co_changes 跳過)。每層缺工具的行為見
design.md 退化矩陣。

## 測試

```bash
python3 -m unittest discover -s tests -t .   # unit / integration / e2e 三層
ruff check . && mypy ccodegraph.py           # lint 閘
```

integration/e2e 在缺 cscope/ctags 的環境自動 skip 並明講;CI 三平台矩陣見
`.github/workflows/ci.yml`。
