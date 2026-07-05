# 第三輪審查 — SKILL.md 可用性(codex 扮演陌生 agent,2026-07-05)

> 驗收法:給 10 個典型任務,看 SKILL 能否讓 agent 選對動詞與旗標。處置:全數採納,SKILL v2。

## 會選錯的地方

| 典型任務 | 我會下的指令 | SKILL 是否足夠 | 可能選錯點 |
|---|---|---|---|
| 誰呼叫 `X` | `ccodegraph.py schema -p <root> --json` → `ccodegraph.py callers X -p <root> --json` | 大致足夠：動詞表有 `callers`，且要求先跑 `schema`。見 [SKILL.md:23](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:23), [SKILL.md:40](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:40) | `--min-conf 0.7` 預設會包含 callback 0.70，陌生 agent 可能把 heuristic callback 當成確定 caller。見 [SKILL.md:48](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:48), [SKILL.md:66](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:66) |
| `X` 呼叫誰 | `ccodegraph.py callees X -p <root> --json` | 足夠。見 [SKILL.md:40](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:40) | 若 `X` 多重定義，文件說 per-definition sections，但沒有輸出範例，agent 不一定知道怎麼引用 qname。見 [SKILL.md:40](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:40), [SKILL.md:96](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:96) |
| 誰寫全域 `V` | `ccodegraph.py globals V -p <root> --json` | 足夠。見 [SKILL.md:42](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:42) | 風險章提醒 name-keyed shadowing，但沒有說 `globals` 輸出如何標註 `semantic:absent` / tags。見 [SKILL.md:76](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:76), [SKILL.md:111](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:111) |
| 函式 `F` 讀寫哪些全域 | `ccodegraph.py vars-of F -p <root> --json` | 足夠。見 [SKILL.md:43](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:43) | 若有同名函式，缺少「先用 `explore` 找 qname，再跑 `vars-of qname`」的明確流程。 |
| 改 `X` 影響誰 | `ccodegraph.py impact X -p <root> -d 2 --json` | 不足。`impact X -d N` 有寫，但沒有教 `N` 怎麼選、預設是多少、什麼時候要 `--ambiguous`。見 [SKILL.md:41](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:41), [SKILL.md:92](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:92) | 陌生 agent 很可能任意選 `-d 2` 或 `-d 3`，或漏掉 `--ambiguous` 而低估爆炸半徑。 |
| 巨集 `M` 哪裡用 | `ccodegraph.py callers M -p <root> --json` | 部分足夠。表格括號說 macros too。見 [SKILL.md:40](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:40) | 但 SQL schema 有 `expands` edge，動詞卻叫 `callers`，陌生 agent 可能改用 `sql` 查 `expands`，或不確定 macro object-like/function-like 是否都適用。見 [SKILL.md:119](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:119) |
| header `H` 影響哪些檔 | `ccodegraph.py who-includes H -p <root> --json` | 只對直接 include 足夠。見 [SKILL.md:44](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:44) | 「header-edit rebuild impact」通常需要直接加間接 include；文件沒說 `who-includes` 是否 transitive，也沒有 `--recursive`。 |
| `#ifdef` 這段有人用嗎 | 我可能先 `schema`，再查相關 symbol 的 `callers` / `callees`，看 `semantic:absent` | 不足。description 觸發了這個任務，但 verb table 沒有對「一段 code / 條件編譯區塊」給明確查法。見 [SKILL.md:3](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:3), [SKILL.md:76](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:76) | Agent 可能誤以為 `semantic:absent` 就等於該 `#ifdef` 有人用，或反過來當成 dead code。 |
| fn pointer / callback dispatch | `ccodegraph.py callers handler -p <root> --json`，必要時 `--min-conf 0.5` | 不足。風險章有 conf 0.80 `fnptr`、0.70 `callback`，但 verb table 沒有明確「查 callback/fnptr 用 callers 還是 impact」。見 [SKILL.md:65](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:65), [SKILL.md:66](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:66) | 陌生 agent 可能漏查 `fnptr` edge，或把 callback heuristic 寫成確定呼叫關係。 |
| 歷史上常一起改的檔案 | `ccodegraph.py co-changed F -p <root> --json` 或 `--min-conf 0.5` | 有矛盾。動詞表說用 `co-changed`；風險章說 git conf 是 0.50；旗標說預設 `--min-conf 0.7`。見 [SKILL.md:45](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:45), [SKILL.md:48](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:48), [SKILL.md:67](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:67) | 若 `co-changed` 沒有特例 bypass threshold，照文件跑會空；若有特例，文件沒說。這是最容易選錯 flag 的地方。 |

## 誤導表述

- `semantic:absent` 的說法太強。文件先說「NOT a false edge」「usually inactive #ifdef」，最後要求 Treat as “real code, not in this build config”。見 [SKILL.md:80](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:80)-[SKILL.md:83](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:83)。但 cscope 本身是 name-keyed、會 shadow 誤配，見 [SKILL.md:64](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:64), [SKILL.md:111](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:111)。建議改成：「未被 active semantic config 確認；常見原因是 inactive config / other platform；仍需看 file:line 排除 name-keyed false edge。」

- callback 0.70 會被預設 threshold 收進來，但文件只說「verify surprising ones」。見 [SKILL.md:48](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:48), [SKILL.md:66](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:66)。這會讓 agent 對不 surprising 的 callback 邊過度自信。應明講：`callback` only 要用「possible caller」措辭，除非讀過 cited site。

- STALE 範圍不清。`schema` 的 STALE 描述集中在 `fnptr.json` / manual edges。見 [SKILL.md:30](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:30)-[SKILL.md:32](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:32), [SKILL.md:61](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:61)。但後面又泛稱「code changed? build --incremental」和「graph only trustworthy when aligned with tree」。見 [SKILL.md:20](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:20), [SKILL.md:143](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:143)。陌生 agent 不知道 `schema` 是否偵測一般 source file drift。

- `agreement is evidence` 很好，但「[cscope, clink] strong」仍只代表 active config + text layer agree，不代表跨所有 build config。見 [SKILL.md:69](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:69)-[SKILL.md:72](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:72)。建議補一句 scoped-to-config。

## 缺漏

- 缺輸出範例。文件說所有 verb 支援 `--json`，但沒有 JSON schema 或文字輸出範例。見 [SKILL.md:35](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:35)。陌生 agent 會卡在：tags 在哪個欄位、ambiguous 長什麼樣、`semantic:absent` 是 tag 還是 meta。

- SQL schema contract 少了 `nodes.id`，但範例大量使用 `n.id`。見 [SKILL.md:117](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:117), [SKILL.md:124](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:124)。這會讓 agent 寫 SQL 時不確定可用欄位。

- `tags` 說是核心判讀依據，但 SQL contract 只有 `meta JSON`，沒有 `tags` 欄位說明。見 [SKILL.md:53](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:53)-[SKILL.md:55](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:55), [SKILL.md:119](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:119)-[SKILL.md:120](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:120)。

- 缺錯誤訊息對照：graph 不存在、build 尚未跑、clink binary 找不到、DB schema mismatch、symbol not found、ambiguous hint、STALE warning，各自下一步是什麼。目前只有空結果處理原則。見 [SKILL.md:141](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:141)-[SKILL.md:142](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:142)。

- 缺 symbol 輸入規則：`X` 是 basename、qname、file path、macro name、header path 時如何 quote / disambiguate。只有一個 qname 例子。見 [SKILL.md:96](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:96)。

- 缺 macro 查詢細節。`callers MAX2` 與 `expands` edge 的關係未定義。見 [SKILL.md:40](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:40), [SKILL.md:119](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:119)。

## 認可之處

- `schema` 作為 Step 0 是正確的，且明確要求先看 engine / STALE / pending layers。見 [SKILL.md:23](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:23)-[SKILL.md:33](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:33)。

- Verb table 對大多數典型 C 任務已經能讓 agent 選到第一個正確動詞：`explore`、`callers`、`callees`、`globals`、`vars-of`、`who-includes`、`co-changed`。見 [SKILL.md:37](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:37)-[SKILL.md:46](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:46)。

- 風險章有把 confidence / origin / tags 分開講，方向正確，特別是 ambiguous impact 預設 skip、必要時 `--ambiguous`。見 [SKILL.md:51](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:51)-[SKILL.md:56](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:56), [SKILL.md:92](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:92)-[SKILL.md:95](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:95)。

- 「graph first, grep last」和「empty result ≠ nothing exists」是 agent 會真正受益的操作準則。見 [SKILL.md:137](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:137)-[SKILL.md:145](/Users/swchen.tw/git/ccodegraph/skills/ccodegraph/SKILL.md:145)。
