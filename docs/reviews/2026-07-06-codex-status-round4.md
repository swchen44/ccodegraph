# 第四輪審查 — status 作為偵錯分診工具(codex 扮演支援工程師,2026-07-06)

> 處置:核心組全採納(health/issues 穩定代碼、status_schema_version、env 拼錯偵測、
> tools.ok/flavor、DB 身份核對、clink 匯入統計、skill stale、compile DB entries、
> engine 一行化、雜訊搬層)。backlog:which_all、source-discovery 明細、
> compile DB 逐檔覆蓋率、deprecated/conflict env 分析。

## 缺欄位(卡住點)

只憑目前 `status` / `status --full`，可以分診：工具是否找得到、實際工具路徑、env override 是否生效、skill 是否未安裝、是否沒有 graph、graph 是否與 source hash 對齊、是否跑過 clink、compile DB 是 synthesized 還是真 compile DB、DB 內 node/edge 總量、最近 history。

會卡住、需要追問的地方如下，建議補具體欄位：

- 工具裝錯版本：目前只有 raw version string，沒有判斷結果。  
  建議：`tools.<name>.exists`, `tools.<name>.executable`, `tools.<name>.resolved_path`, `tools.<name>.version_raw`, `tools.<name>.version_parsed`, `tools.<name>.flavor`, `tools.<name>.min_required`, `tools.<name>.version_ok`, `tools.<name>.error`, `tools.<name>.which_all`。

- env var 打錯字：目前只列已知 env，拼錯的 `CCODEGRAPH_*` 會完全看不到。  
  建議：`env.known`, `env.unknown_ccodegraph_vars`, `env.deprecated_vars`, `env.conflicts`, `env.effective_overrides`。

- DB 是否用錯、過期、或不是這個 root 建的：目前有 drift，但缺 DB 身分核對。  
  建議：`db.effective_path`, `db.exists`, `db.managed_by_status_reset`, `db.root_recorded`, `db.root_matches_current`, `db.schema_version`, `db.schema_expected`, `db.schema_ok`, `db.mtime`, `db.age_seconds`, `db.built_at_git`, `db.git_now`, `db.git_matches`, `db.last_successful_action`。

- compile DB 沒吃到：目前只能從 engine mode 猜，無法知道涵蓋率。  
  建議：`compile_db.mode`, `compile_db.source`, `compile_db.path`, `compile_db.entries`, `compile_db.covered_source_files`, `compile_db.total_source_files`, `compile_db.missing_source_files`, `compile_db.conflicts`, `compile_db.mode_changed_since_last_import`, `compile_db.defines_present`, `compile_db.include_paths_present`。

- clink import 是否真的健康：目前有 clink engine 記錄，但缺匯入結果摘要。  
  建議：`clink.enabled`, `clink.db_path`, `clink.db_exists`, `clink.user_version`, `clink.user_version_ok`, `clink.mode`, `clink.confidence`, `clink.calls_imported`, `clink.writes_imported`, `clink.dropped_no_src`, `clink.semantic_confirmed`, `clink.semantic_absent`, `clink.last_error`。

- skill 沒裝 vs 裝錯版本：目前只知道 installed paths，不知道內容是否過期。  
  建議：`skill.installed_paths`, `skill.search_dirs`, `skill.expected_hash`, `skill.installed_hashes`, `skill.version`, `skill.stale`, `skill.precedence_path`, `skill.install_hint`。

- graph 品質異常：只有總 nodes/edges，不足以判斷哪層壞掉。  
  建議：`artifact.node_counts_by_kind`, `artifact.edge_counts_by_kind_origin`, `artifact.confidence_counts`, `artifact.semantic_counts`, `artifact.pending_layers`, `artifact.zero_edge_kinds`。

- source 掃描範圍錯：目前看不到 source discovery 結果。  
  建議：`source.files_count`, `source.extensions`, `source.root`, `source.ignored_dirs`, `source.sample_files`, `source.zero_sources`, `source.header_count`, `source.c_count`, `source.cpp_count`。

- drift 細節不足：預設只列前 5 個檔，full 文字也沒有全列。  
  建議：`drift.files_changed`, `drift.files_added`, `drift.files_deleted`, `drift.truncated`, `drift.total`。

- 自動化分診缺結論碼：目前只有自然語言 `suggestion`。  
  建議：`health.overall`, `issues[]`, `issues[].code`, `issues[].severity`, `issues[].evidence`, `issues[].action`, `status_schema_version`。

## 分層調整

預設版方向合理：應該是「支援第一眼能判斷該叫使用者做什麼」。但現在預設有些資訊太 raw，有些關鍵結論不夠明確。

建議預設版保留或新增：

- `health.overall` / 一行總結，例如 `OK`, `NO_GRAPH`, `STALE_GRAPH`, `TOOL_MISSING`, `CLINK_SYNTHESIZED`, `SKILL_MISSING`。
- effective root/db：`root`, `db.effective_path`, `db.exists`。
- tools 摘要：每個工具 `ok/path/version/env_override`。
- skill 是否 installed；未安裝時保留 install hint。
- graph freshness：`drift.total`, `built_at_git`, `git_now`。
- compile DB / clink mode 摘要，因這是常見支援問題，應在預設版可見。
- artifact 摘要：schema、nodes、edges、last action。

建議搬到 `--full`：

- 所有 `(unset)` env var 列表。預設只列有效 override 即可。
- `products` 逐項檔案列表。
- `databases` 全列表與長說明文字；預設只顯示 effective DB 和其他 DB count。
- raw `engine: {'engine': ...}` dict；預設應格式化成一行摘要，raw JSON 留給 `--json`。
- history 5 筆。預設保留 last action 即可。

建議 `--full` 新增：

- 全 drift 檔案清單。
- source discovery summary。
- compile DB coverage。
- edge/node by-kind counts。
- skill search dirs 與 hash/version。
- tool resolution diagnostics，例如 `which_all`、permission、非 Universal Ctags 判斷。

## 雜訊

- `databases:` 後面的長括號說明對每次 debug 幫助有限，建議改成 `hints[]` 或只在 `--full` 顯示。
- `products --full` 裡 `.gitignore 2 B` 幾乎沒有分診價值，建議標成 `internal=true` 或預設 full 也可略過 internal trivial files。
- text mode 的 `engine: {'engine': ...}` 是 Python dict 形狀，對人讀不順，也不利於貼到 issue。建議改成固定格式：`engine: clink mode=synthesized entries=8 conf=0.8 seconds=0.3`。
- `platform` raw string 可保留，但不用再擴張；真正支援價值更高的是 `ccodegraph_path`, `cwd`, `argv`, `root_arg`, `db_arg`。
- `products` byte size 對 debug 價值低於 mtime、存在性、來源模式；size 可以保留在 JSON，文字版可簡化。

## 認可

目前設計已經抓到支援分診的主幹：工具路徑與版本、env override、skill 安裝、DB/product 存在性、artifact schema/node/edge、engine history、source drift。預設版 vs `--full` 的大方向也合理。

`--json` 目前可被腳本解析，但還不夠做穩定自動分診；主要問題不是 JSON 格式，而是缺少 stable health codes、ok/error 布林欄位、coverage 統計與 DB/compile DB/skill 的身分核對欄位。最值得優先補的是：

`status_schema_version`, `health.overall`, `issues[]`, `db.*`, `tools.*.version_ok`, `env.unknown_ccodegraph_vars`, `compile_db.*`, `clink.*`, `skill.stale`, `artifact.edge_counts_by_kind_origin`。
