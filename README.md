# ccodegraph — C/C++ 知識圖譜(C 優先、多引擎、標注出處與信心)

把三家實測解剖的長處拼成一張圖:cbm 的邊分類學 + confidence、CodeGraph 的邊站點 +
分節輸出、ccq/cscope 的 C 召回。純 Python 標準庫;外部只依賴 `cscope`、`universal-ctags`
(之後的層:tree-sitter、clangd、git)。

- 設計:[docs/design.md](docs/design.md)(schema、邊分類學、信心分數表、D1–D3 決定)
- 需求:[docs/requirement.md](docs/requirement.md)

```bash
./ccodegraph.py build -p <repo>     # L0 ctags 節點 + L1 cscope 邊 → <repo>/.ccodegraph/graph.db
./ccodegraph.py schema -p <repo>    # 第一動詞:格子清單 + 填充率 + 未填的層
./ccodegraph.py callers X -p <repo> # 同名多定義 → 分節(D1)
./ccodegraph.py globals V / vars-of F / impact X -d 3 / who-includes H / sql '…'
```

測試(標準庫 unittest;integration/e2e 需要 cscope + universal-ctags):

```bash
python3 -m unittest discover -s tests -v
```
