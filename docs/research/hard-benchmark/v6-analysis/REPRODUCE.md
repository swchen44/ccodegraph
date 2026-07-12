# v6 複現指引(LSP 對決 + 診斷探針 + 精調臂)

對應報告:`docs/research/llm-ab-v6-lsp.md`。本目錄含全部腳本、plugin、
compile DB、SKILL 版本與評分 schema;照本文逐步可完整重現三個實驗
(v6 主對決、hint-probe 診斷、lsp-skill 精調臂)。預算參考:主對決
~$60、hint-probe ~$3、精調臂 ~$32(runs+smoke);codex 評分走訂閱。

## 0. 前置環境

| 需求 | 版本(當時) | 檢查 |
|---|---|---|
| Claude Code CLI | 2.1.206(≥2.1.205) | `claude --version` |
| clangd | Apple clangd 17(PATH 上任一 clangd 皆可) | `clangd --version` |
| codex CLI(評分者) | 訂閱登入 | `codex --version` |
| python3 | ≥3.10,標準庫 | |
| 受測 repo | wpa_supplicant、redis 的 git checkout(commit 見 compdb 內路徑對應的 v2/v3 建置) | |

**compile DB**:`compdb-wpa.json`(112 entries,真實 build:
CONFIG_DRIVER_WIRED+SAE+AP 組態,driver_nl80211.c 缺席=已知限制)、
`compdb-redis.json`(357 entries 含 deps/,bear 產出,內含 4 條
configure 幽靈條目 foo.c——harness 會自動跳過)。放到各 repo 根目錄
命名 `compile_commands.json`;內含產生機的絕對路徑,**harness 會在
解樹時自動重寫前綴**(directory/file/output/arguments 四處),不必手改。
重新生成方法:wpa 用 `make V=1` 記錄改寫、redis 用 `bear -- make`。

## 1. clangd LSP plugin 安裝(一次性)

`clangd-plugin/` 就是完整的本地 marketplace:

```bash
claude plugin marketplace add <abs-path>/clangd-plugin
# 之後由 harness 在每個工作樹寫 .claude/settings.json 啟用
# (enabledPlugins: {"clangd-lsp@local-bench": true}, scope=project)
```

已實測:headless(`claude -p`)+ `--setting-sources project` 下 plugin
LSP 完整可用;agent 拿到 deferred tool `LSP`(九操作,詳報告 §3)。
坑:clangd **惰性載入** compile DB——harness 的預熱器會 `didOpen`
一個 DB 內檔案觸發 background index,漏這步 = 0 shards。

## 2. 路徑設定

`run_hard_ab_v6.py` 頂部常數:`REPOS`(兩個 checkout 路徑)、
`CCODEGRAPH_REPO`、`V6_WORK`(工作樹/預熱快取根)、`CLINK_BIN`(選配)。
SKILL 檔:精調臂讀 `$V6_WORK/skill/SKILL-current.md`——複現時
`cp SKILL-v2.md $V6_WORK/skill/SKILL-current.md`(v1/v2 皆在本目錄,
迭代差異只有「長清單分段」段落,動機與勘誤見報告增補 2)。

## 3. 實驗一:v6 主對決(22 題 × 3 臂 × N=3 = 198 runs)

```bash
python3 run_hard_ab_v6.py <out_dir>                 # 全量(可中斷,resume 以 (id,tool,rep) 為鍵)
python3 run_hard_ab_v6.py <out_dir> WRQ-004 reps=1 tools=lsp   # 單題單臂
```

條件(嚴禁改動,否則與報告不可比):`claude-sonnet-5`、
`--max-budget-usd 3`、`--setting-sources project`、循序執行、
題→rep→臂序。三臂 prompt 在腳本內(=報告附錄 A)。
lsp 臂用固定工作樹 + 指紋防污染 + clangd 預熱(wpa ~22s/235 shards、
redis ~24s/379,計入索引成本表)。

評分(66 次,3-slot,**ANS_CAP=12000**——v6.1 協定,4000 會截斷長答案
誤導評分者,教訓詳報告 §6):

```bash
python3 score_v6.py <out_dir> <scores_dir>
python3 analyze_v6.py        # 分數矩陣/總分/變異/LSP 使用率(路徑在腳本頂部)
```

預期(v6.1):none 60 / ccodegraph 63 / lsp 60(/66);
LSP 使用率:24/66 runs 零使用、incomingCalls 全場 4 次。

## 4. 實驗二:hint-probe 診斷(9 runs)

```bash
python3 hint-probe/hint_probe.py     # WRQ-009/019/016 × 3 reps,提示版 prompt
```

評分用 1-slot(`score_schema_1slot.json`,rubric 同 3-slot)。預期:
WRQ-019 與 WRQ-016(負對照)升分的 run **零 LSP 呼叫**——起效的是
覆核紀律半句,不是使用時機半句(9 runs 僅 2 個碰 LSP)。

## 5. 實驗三:lsp-skill 精調臂(66 runs)

```bash
cp SKILL-v2.md $V6_WORK/skill/SKILL-current.md
rm -rf $V6_WORK/work-lspskill-*      # 強制以當前 SKILL 重備樹(指紋不追蹤 skill 內容)
python3 run_hard_ab_v6.py <skill_out> tools=lspskill
python3 score_lspskill.py <skill_out> <skill_scores>
python3 analyze_lspskill.py <skill_out> <skill_scores> <v6_scores_dir>
```

預期:**61/66**;升分題 WRQ-013/015(移植紀律),WRQ-008 rep 噪音回落;
skill 觸發 64/66;LSP 呼叫 117→92 但 call-hierarchy 5→26。

## 6. 已知陷阱清單(每條都踩過)

1. clangd 惰性載入 compile DB(§1);`filePath:"."` 或裸檔名報錯。
2. compile DB `file` 欄可為相對 `directory` 的路徑;bear 幽靈條目。
3. 評分視窗必須 ≥ 最長答案(v6.1;稽核指令:掃 runs 目錄 `result`
   長度 >ANS_CAP 者必須重評)。
4. smoke N=1 會樂觀(WRQ-019 smoke 3 → 全量中位 2);結論只認 N=3。
5. 固定工作樹跨 run 共用時,任何樹內容變更(含 SKILL 換版)要強制重備。
6. `LSP` 是 deferred tool,agent 需 ToolSearch 載入(prompt 已教)。

## 7. 本目錄檔案索引

| 檔案 | 用途 |
|---|---|
| `run_hard_ab_v6.py` | harness(四臂 prep + 執行 + resume;與 `tools/` 同步的凍結副本) |
| `score_v6.py` / `score_schema.json` | 3-slot 評分器(v6.1 ANS_CAP=12000) |
| `score_lspskill.py` / `score_schema_1slot.json` | 1-slot 評分器 |
| `analyze_v6.py` / `analyze_lspskill.py` | 分析(矩陣/總分/使用率遙測) |
| `clangd-plugin/` | 本地 marketplace + clangd-lsp plugin(原樣可 add) |
| `compdb-wpa.json` / `compdb-redis.json` | 真實 compile DB(v2/v3 建置產物) |
| `lsp-skill/SKILL-v1.md` / `SKILL-v2.md` | 教學層兩個版本(迭代記錄見報告) |
| `hint-probe/` | 診斷探針腳本 + 9 份 runs/scores |
| `lsp-index-meta-*.json` | clangd 預熱計時/shard 數 |
| `analysis-output.txt` | v6.1 修正後的分析輸出存檔 |
| `../v6-runs*` `../v6-scores*` | 全部原始執行與評分 JSON(含 `*.pre-v61` 勘誤前存檔) |
