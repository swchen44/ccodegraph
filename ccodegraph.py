#!/usr/bin/env python3
"""ccodegraph — C/C++ 知識圖譜(C 優先 80%,C++ 輕量 20%):多引擎分層填料、逐筆標注 origin/confidence。

Python 標準庫 only。外部 binary:cscope、universal-ctags(L0/L1);
後續層(tree-sitter/clangd/git)缺工具時明講跳過,不靜默(NFR1/P7)。

Schema 與決策見 docs/design.md。本檔實作:
- L0 ctags 節點 + L1 cscope 邊(calls/reads/writes/includes)
- L3 callback(fn-as-argument)+ fnptr(field-keyed 分派)+ manual 表(fnptr.json)
歸戶規則(D1):src 用行區間精確判定;dst 先套 static 同檔規則(header 例外:
static inline in .h 可被 includer 呼叫),殘餘非 static 同名 → 一對多掛靠 +
ambiguous 註記(D3)。D4(codex review 後拍板):ambiguous 邊 callers 顯示、
impact 預設不走(--ambiguous 全開);查詢預設門檻 confidence >= 0.7。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import select
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

VERSION = "0.0.6"

Def = dict[str, Any]          # 節點 dict:name/kind/file/line_start/line_end/is_static/qname/id
CscopeRow = tuple[str, str, int, str]   # (field2, file, line, text)

PRODUCTS_DIR = ".ccodegraph"          # 所有中間產物集中此處(ccq 經驗:不污染使用者空間)
DB_NAME = os.path.join(PRODUCTS_DIR, "graph.db")

# --- EMBEDDED_SKILL_BEGIN(由 tools/embed_skill.py 生成,勿手改)---
SKILL_MD = '''\
---
name: ccodegraph
description: Invoke FIRST, before running any ccodegraph.py command — this file embeds the complete command cheatsheet, DB schema, and token discipline (without it you will waste calls discovering syntax). Use when navigating or refactoring C/C++ — who calls a function, what it calls, who reads/writes a global, who uses a macro, impact of a change, fn-pointer/callback dispatch, files including a header, co-changing files. Triggers on "誰呼叫", "who calls", "callers of", "who writes", "impact of", "爆炸半徑", "巨集哪裡用", "co-change", or any task needing many grep/Read calls over C/C++. Zero build needed. Every answer carries origin + confidence + tags. C first-class; C++ best-effort.
---

# ccodegraph — C/C++ knowledge graph (SQLite, honesty-labelled)

One graph at `<root>/.ccodegraph/graph.db`; every edge stamped **origin +
confidence + tags**. **If `graph.db` exists the graph is ready — query it
directly. Do NOT run `build`/`schema`/`status` first.** Only two exceptions:
a query errors `no graph` → `build -p <root>` once; you just edited source →
`build --incremental` (cheap, exact) then re-query.

## Command cheatsheet (copy exactly — this file is the complete reference; never run `--help`)

```bash
./ccodegraph.py explore <sym> -p .        # def(file:line,signature)+callers+callees+globals — DEFAULT first move
./ccodegraph.py callers <sym> -p .        # deduped callers, one site + (N sites); includes [fnptr]/[callback] indirect
./ccodegraph.py callees <sym> -p .
./ccodegraph.py impact <sym> -d 2 -p .    # change radius; if it hints about ambiguous edges, rerun with --ambiguous
./ccodegraph.py globals <var> -p .        # writers vs readers, separated
./ccodegraph.py vars-of <fn> -p .         # globals <fn> touches, [reads]/[writes]
./ccodegraph.py who-includes <hdr> -p .   # DIRECT includers, all #include spelling variants, deduped
./ccodegraph.py co-changed <file> -p .    # git co-change statistics (conf 0.50, not semantics)
./ccodegraph.py sql "SELECT … LIMIT 50" -p .   # read-only escape hatch; ALWAYS LIMIT or aggregate
```

`<sym>` = plain name (`eloop_init`) or qname `'src/utils/eloop.c::eloop_init'`
(quote it). Same name defined in several places → per-definition sections; pin
one with the qname. All verbs take `--json`; flags: `--min-conf 0.7` (default),
`--ambiguous`, `--db <path>`, `--limit N`.

Sample (`callers app_init`): `- do_start @ caller.c:3 (2 sites) [cscope; ambiguous 2 candidates; semantic:confirmed]`

**Output caps**: `callers`/`callees`/`explore` print ≤40 rows per section, then
`… +N more (total T; use --limit 0 for all)`; `sql` stops at 200 rows with an
explicit truncation notice. The TRUE TOTAL is always reported — for a full
enumeration rerun with `--limit 0` or a scoped sql query; never treat a
truncated list as complete.

## Token discipline (measured — this is what makes the graph pay for itself)

1. **Graph first, then narrow Read**: the graph cites exact `file:line` — Read
   with offset/limit around it. Never whole-file Read, never `ls` the repo root
   (file list: `sql "SELECT qname FROM nodes WHERE kind='file' AND qname LIKE '%x%' LIMIT 20"`).
2. **Scope queries to the question**: asked about one file/dir? Filter in SQL —
   `sql "SELECT s.qname,e.file,e.line FROM edges e JOIN nodes s ON s.id=e.src
   JOIN nodes d ON d.id=e.dst WHERE d.name='X' AND e.kind='calls' AND e.file
   LIKE 'src/foo%'"` — do NOT run bare `callers` on a high-fan-in symbol
   (hundreds of rows for zero value).
3. `explore` already bundles callers+callees+globals — don't re-query them
   separately.
4. **Before claiming any total, cross-check with one `COUNT(*)` query** — one
   cheap row that catches the classic hand-tally error.
5. Stay in the repo root and use `-p .`; don't `cd` around.

## Schema (embedded — no need to run the `schema` verb)

```
nodes(id, name, qname, kind: function|global|macro|file, file,
      line_start, line_end, signature, is_static, origin, confidence)
edges(src→nodes.id, dst→nodes.id,
      kind: calls|callback|fnptr|reads|writes|includes|expands|co_changes,
      file, line, origin, confidence, meta JSON)      -- one row per SITE
edge_pairs view (src,dst,kind,confidence,first_site,site_count,origins)  -- one row per PAIR
```

## Reading the labels (trust calibration — say what the label says)

conf 1.00 `manual` (user assertion, not proof) · 0.95 `clink`+real compile DB
(single build config only) · 0.93 `clink`+synthesized DB · 0.90 `cscope`
(name-keyed, `#ifdef`-blind: great recall, same-named symbols can mis-bind) ·
0.80 `fnptr` heuristic (field-keyed: `->run()` links every registered `run`) ·
0.70 `callback` (the only signal for qsort-comparator/timer questions — phrase
as "possible caller via callback" unless you read the cited site) · 0.50 `git`.

`[cscope, clink]` on one edge = two independent engines agree (within the
active config). `semantic:confirmed` = clink also saw it (token-level, includes
inactive `#ifdef` regions). `semantic:absent` = clink never successfully parsed
there — a coverage flag, NOT a falsity signal. `ambiguous N candidates` =
same-name definitions; the edge is attached to every viable one — pin by qname;
`impact` skips ambiguous by default (rerun `--ambiguous` when it hints).

## Blind spots — flag these proactively when answer-relevant

- **Struct-field fn-pointer dispatch** (`c->ops->run(c)`): no direct call edge
  exists; `fnptr`/`callback` edges are heuristic. Verify the registration site
  before asserting a dispatch target.
- Macro-GENERATED definitions (`DEFINE_X(foo)` → `foo_handler`): invisible to
  text engines — `sql` LIKE-hunt the generator, then read the macro.
- **Config-dependent code has TWO gating mechanisms**: in-file `#ifdef` AND
  build-system file gating (`Makefile`: `ifdef X … OBJS += foo.o` compiles whole
  files only under a flag — such files often contain zero `#ifdef` themselves).
  For any "what depends on CONFIG_X" question, grep the Makefiles too.
- Object-like macro usage, C++ templates/overloads, computed `#include`: not
  (fully) modelled — fall back to scoped grep.
- Empty result ≠ nothing exists: retry `--min-conf 0.5`, then
  `sql "…name LIKE '%X%'"`, then grep.

## Errors

`no graph` → `build -p <root>` · `symbol not found` → sql LIKE hunt ·
`fnptr … STALE` → rebuild · `clink not found` → optional layer, skip it.

Other verbs (`viz`/`status`/`reset`/`dumpdb`/`skill`/`build`/`clink-import`)
are setup/human-facing — not needed to answer code questions.
'''
# --- EMBEDDED_SKILL_END ---
CSCOPE_DB = os.path.join(PRODUCTS_DIR, "cscope.out")   # 專用索引,集中產物目錄(FR6)
HEADER_EXTS = (".h", ".hpp", ".hh")
FANOUT_CAP = 16                          # fnptr field 註冊數上限(超過視為雜訊)
DEFAULT_MIN_CONF = 0.7
# D16(2026-07-08):顯式截斷。真實 benchmark 中高扇入符號的 callers 全量列印
# 單次回傳 27.8KB(decrRefCount,數百 caller,而題目只問一個檔案)——預設截斷
# 並「必印真實總數」,agent 需要全量時 --limit 0;隱性截斷會毀掉枚舉題的正確性,
# 所以截斷永遠顯式、總數永遠可見。sql 逃生口另設行數上限(--limit 可覆蓋)。
DEFAULT_LIST_LIMIT = 40                  # callers/callees/explore 每節預設上限
SQL_ROW_CAP = 200                        # sql 逃生口預設行數上限

# design.md §3 — confidence 只表達「產生引擎的固有準確率」(D3)
CONFIDENCE: dict[str, float] = {
    "manual": 1.00,
    "ctags": 0.95,
    "clangd": 0.95,
    "cscope": 0.90,
    "cindex": 0.90,
    "treesitter": 0.85,
    "fnptr": 0.80,
    "clink": 0.93,
    "clangd-nobuild": 0.75,
    "callback": 0.70,
    "git": 0.50,
}

# schema 動詞回報「格子還空著」用(design.md §5 填料計畫)
PENDING_LAYERS: list[tuple[str, str]] = [
    ("fnptr", "L3: ops/vtable 分派邊 + manual 表"),
    ("callback", "L3: fn-as-argument 邊"),
    ("clink", "R7a: libclang 解析期歸戶 calls + 語意 writes(選配,需 clink binary)"),
    ("clangd", "L4: 高信心 calls/uses_type/signature 升級(需 compile DB)"),
]

# B3:次要索引拆出——54.8M 邊的全樹建圖,邊插邊維護索引是寫入大頭;
# bulk load 後一次建立快得多。SCHEMA_SQL(公開合約)仍含全部索引。
SCHEMA_INDEXES_SQL = """
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_edges_src ON edges(src);
CREATE INDEX idx_edges_dst ON edges(dst);
"""

SCHEMA_BASE_SQL = """
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (
  path TEXT PRIMARY KEY, lang TEXT, content_hash TEXT,
  indexed_at TEXT, git_rev TEXT);
CREATE TABLE nodes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, qname TEXT NOT NULL, kind TEXT NOT NULL,
  file TEXT NOT NULL, line_start INTEGER, line_end INTEGER,
  signature TEXT, is_static INTEGER DEFAULT 0,
  module TEXT DEFAULT '',
  origin TEXT NOT NULL, confidence REAL NOT NULL,
  metrics TEXT DEFAULT '{}',
  UNIQUE(qname, kind));
CREATE TABLE edges (
  id INTEGER PRIMARY KEY,
  src INTEGER NOT NULL REFERENCES nodes(id),
  dst INTEGER NOT NULL REFERENCES nodes(id),
  kind TEXT NOT NULL, file TEXT, line INTEGER,
  origin TEXT NOT NULL, confidence REAL NOT NULL,
  meta TEXT DEFAULT '{}',
  UNIQUE(src, dst, kind, origin, file, line));
CREATE VIEW edge_pairs AS
  SELECT src, dst, kind, MAX(confidence) AS confidence,
         MIN(printf('%s:%09d', file, line)) AS first_site,
         COUNT(*) AS site_count,
         GROUP_CONCAT(DISTINCT origin) AS origins
  FROM edges GROUP BY src, dst, kind;
CREATE VIEW file_deps AS
  SELECT DISTINCT e.file AS src_file, n2.file AS dst_file, e.kind
  FROM edges e JOIN nodes n2 ON e.dst = n2.id
  WHERE e.file IS NOT NULL AND e.file != n2.file;
"""

SCHEMA_SQL = SCHEMA_BASE_SQL + SCHEMA_INDEXES_SQL


# ---------------------------------------------------------------- 純函式層
# (unit test 直接打這些;不碰 subprocess / sqlite)

STATIC_RE = re.compile(r"\bstatic\b")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
REG_RE = re.compile(r"[.>]\s*(\w+)\s*=\s*&?\s*(\w+)")      # .field = fn / ->field = fn
DISPATCH_RE = re.compile(r"(?:->|\.)\s*(\w+)\s*\(")          # obj->field( / obj.field(
INCLUDE_RE = re.compile(r'#\s*include\s*[<"]([^>"]+)[>"]')
RMW_RE = re.compile(r"\+\+|--|[+\-*/%|&^]=|<<=|>>=")
CB_PREV = {"(", ",", "&"}
CB_NEXT = {",", ")"}


def detect_static(lines: list[str], line_no: int) -> bool:
    """定義行含 `static` token;或上一行含且未以 ;/}/{ 結尾(K&R 換行式:
    `static int\nfoo(...)`)。上一行是完整敘述(如 `static ... OPS = {...};`)
    時不得波及下一行的定義——ops.c fixture 抓到的誤判。"""
    i = line_no - 1
    if 0 <= i < len(lines) and STATIC_RE.search(lines[i]):
        return True
    j = line_no - 2
    return (0 <= j < len(lines) and bool(STATIC_RE.search(lines[j]))
            and not lines[j].rstrip().endswith((";", "}", "{")))


def assign_qnames(defs: list[Def]) -> list[Def]:
    """D1 消歧名:static → `file::name`;非 static 同名多定義 → 全部 `file::name`;
    同檔仍撞名(#ifdef 分支各定義一次)→ 再加 `:line`;其餘 → `name`。"""
    groups: dict[tuple[str, str], list[Def]] = {}
    for d in defs:
        groups.setdefault((d["name"], d["kind"]), []).append(d)
    seen: set[tuple[str, str]] = set()
    for grp in groups.values():
        dup = len(grp) > 1
        for d in grp:
            q = f'{d["file"]}::{d["name"]}' if d.get("is_static") or dup else str(d["name"])
            if (q, d["kind"]) in seen:                 # 同檔 #ifdef 雙定義
                q = f'{q}:{d["line_start"]}'
            seen.add((q, d["kind"]))
            d["qname"] = q
    return defs


def attribute_src(index: dict[str, list[Def]], name: str, file: str, line: int) -> Def | None:
    """src 歸戶(D1,精確優先):行區間包含 → 同檔唯一 → 全域唯一;否則 None(寧可漏報)。"""
    cands = index.get(name, [])
    hit = [c for c in cands
           if c["file"] == file and c["line_start"] <= line <= c["line_end"]]
    if len(hit) == 1:
        return hit[0]
    same_file = [c for c in cands if c["file"] == file]
    if len(same_file) == 1:
        return same_file[0]
    if len(cands) == 1:
        return cands[0]
    return None


def choose_dst(cands: list[Def], site_file: str) -> list[Def]:
    """dst 歸戶(D1):static 只可能被同檔呼叫(C 語意)——**header 例外**:
    static inline 定義在 .h,經 #include 對所有 includer 可見(codex 致命問題 3)。
    回傳 viable list——len==1 判定,>1 掛全部標 ambiguous(D3),0 放棄。"""
    return [c for c in cands
            if not c["is_static"] or c["file"] == site_file
            or str(c["file"]).endswith(HEADER_EXTS)]


def edge_meta(viable_count: int, extra: dict[str, Any] | None = None) -> str:
    """D3 註記:非 static 同名一對多掛靠時標 ambiguous。"""
    m: dict[str, Any] = dict(extra or {})
    if viable_count > 1:
        m.update({"ambiguous": True, "candidates": viable_count,
                  "rule": "non-static-dup"})
    return json.dumps(m, sort_keys=True) if m else "{}"


def strip_c_line(line: str, in_block: bool) -> tuple[str, bool]:
    """去除字串常值與註解(// 與 /* */,含跨行狀態)——L3 文字掃描的防誤報前處理。"""
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if in_block:
            j = line.find("*/", i)
            if j < 0:
                return "".join(out), True
            i, in_block = j + 2, False
            continue
        c = line[i]
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            in_block = True
            i += 2
            continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c in "\"'":
            q = c
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == q:
                    i += 1
                    break
                i += 1
            out.append(q + q)          # 佔位,避免前後 token 黏合
            continue
        out.append(c)
        i += 1
    return "".join(out), in_block


def callback_hits(clean: str, names: set[str]) -> list[str]:
    """fn-as-argument 偵測(ccq 實測規則):識別字前一個非空白字元 ∈ {(,&}
    且後一個 ∈ {,)} → 函式被當值傳遞(qsort 比較器、signal handler)。"""
    hits: list[str] = []
    for m in IDENT_RE.finditer(clean):
        name = m.group(0)
        if name not in names:
            continue
        j = m.start() - 1
        while j >= 0 and clean[j] == " ":
            j -= 1
        prev = clean[j] if j >= 0 else ""
        k = m.end()
        while k < len(clean) and clean[k] == " ":
            k += 1
        nxt = clean[k] if k < len(clean) else ""
        if prev in CB_PREV and nxt in CB_NEXT:
            hits.append(name)
    return hits


def is_rmw(text: str, name: str) -> bool:
    """write 站點同時也是 read:x++ / x += / x = x + 1(codex 高風險 5)。"""
    if RMW_RE.search(text):
        return True
    return len(re.findall(rf"\b{re.escape(name)}\b", text)) >= 2


def include_matches(spec: str, header_relpath: str) -> bool:
    """#include 內容 vs header 路徑:含目錄的 spec 用後綴精確比對,
    純檔名比對 basename(重名 header 錯連防線,codex 高風險 4)。"""
    if "/" in spec:
        return header_relpath == spec or header_relpath.endswith("/" + spec)
    return os.path.basename(header_relpath) == spec


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def compute_changes(old: dict[str, str], new: dict[str, str]) \
        -> tuple[set[str], set[str], set[str]]:
    """(changed, added, deleted)——L5 增量的失效單位是檔案 hash(FR7)。"""
    changed = {p for p in new if p in old and old[p] != new[p]}
    added = set(new) - set(old)
    deleted = set(old) - set(new)
    return changed, added, deleted


def co_change_groups_to_pairs(groups: list[list[str]], cap: int = 20,
                              min_count: int = 2) -> list[tuple[str, str, int]]:
    """git 共變(L5):同 commit 檔案組 → 檔案對計數。超過 cap 的巨型 commit
    略過(合併/重排噪音);count >= min_count 才成邊。純函式,unit 可測。"""
    from collections import Counter
    cnt: Counter[tuple[str, str]] = Counter()
    for g in groups:
        gs = sorted(set(g))
        if len(gs) < 2 or len(gs) > cap:
            continue
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                cnt[(gs[i], gs[j])] += 1
    return [(a, b, c) for (a, b), c in cnt.items() if c >= min_count]


def load_module_map(path: str) -> list[tuple[re.Pattern[str], str]]:
    """R8:module_mapping.csv — 欄1 regex(對檔案路徑,英文不分大小寫),
    欄2 module 名(可中文)。# 開頭行與空行跳過;壞 regex 大聲死(P7)。"""
    import csv as _csv
    rules: list[tuple[re.Pattern[str], str]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(_csv.reader(fh), 1):
            if not row or row[0].strip().startswith("#") or not row[0].strip():
                continue
            if len(row) < 2 or not row[1].strip():
                sys.exit(f"ERROR: module map line {i}: 需要「regex,module」兩欄")
            try:
                pat = re.compile(row[0].strip(), re.IGNORECASE)
            except re.error as e:
                sys.exit(f"ERROR: module map line {i}: bad regex: {e}")
            rules.append((pat, row[1].strip()))
    return rules


def module_of(rules: list[tuple[re.Pattern[str], str]], path: str) -> str:
    """首個命中的 regex 之 module 名;無命中 → 空字串(順序=優先權)。"""
    for pat, mod in rules:
        if pat.search(path):
            return mod
    return ""


# ---------------------------------------------------------------- 外部工具層

CTAGS_INSTALL_HINTS = """ERROR: ccodegraph 需要 Universal Ctags(偵測到:{flavor})
安裝:
  macOS   : brew install universal-ctags   (系統內建的是 BSD ctags,不相容)
  Linux   : apt/dnf install universal-ctags(舊發行版給的是 Exuberant,不相容)
  Windows : choco install universal-ctags / scoop install universal-ctags
為什麼硬性要求:我們依賴 --output-format=json 與 end: 欄位(行區間歸戶,D1),
Exuberant/BSD 皆無此能力;參數也不相容(--kinds-C vs --c-kinds vs 無 kind)。"""


def classify_ctags(version_output: str) -> str:
    """ctags --version 輸出 → universal | exuberant | bsd(NFR3/R2)。
    BSD ctags 不認 --version(輸出 usage 或空)。"""
    low = version_output.lower()
    if "universal ctags" in low:
        return "universal"
    if "exuberant ctags" in low:
        return "exuberant"
    return "bsd"


def require_universal_ctags() -> None:
    try:
        r = subprocess.run([tool_path("ctags"), "--version"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit(CTAGS_INSTALL_HINTS.format(flavor="not installed"))
    flavor = classify_ctags(r.stdout + r.stderr)
    if flavor != "universal":
        sys.exit(CTAGS_INSTALL_HINTS.format(flavor=flavor))


def tool_path(name: str) -> str:
    """工具路徑解析(#3):CCODEGRAPH_<NAME>_PATH 環境變數優先,未設定
    直接吃系統 PATH。例:CCODEGRAPH_CSCOPE_PATH=/opt/bin/cscope。
    (libclang 不在此列:我們不直接呼叫它,它是 clink 建置期連結的。)"""
    return os.environ.get(f"CCODEGRAPH_{name.upper()}_PATH", name)


def run_checked(cmd: list[str], cwd: str) -> str:
    """外部工具失敗要大聲(P7,codex 高風險 3):非零 return code → 帶 stderr 終止。"""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: {' '.join(cmd[:2])} failed (rc={r.returncode}): "
                 f"{r.stderr.strip()[:400]}")
    return r.stdout


CSCOPE_SKIPPED: list[tuple[str, str]] = []  # (symbol, stderr) — build() 結尾彙整警告

_CSCOPE_HEADER_RE = re.compile(rb"cscope: (\d+) lines$")
_CSCOPE_NO_RESULT = b"Unable to search database"  # line-mode 的「查無結果」回覆
_CSCOPE_QUERY_TIMEOUT = 120.0   # 常駐查詢單次上限;實測 kernel 級單發也 <1s


class CscopeWorker:
    """D17:cscope line-mode(`-dl`)常駐行程,索引只載入一次。

    協定(cscope 15.9 實測):啟動印 `>> ` 提示符(無換行);送
    `<qflag><sym>\\n` 後回 `cscope: N lines` 標頭 + N 行結果(格式與
    `-L` 一字不差),再回提示符。提示符無換行 → 會黏在下一個標頭前
    (`>> cscope: 12 lines`),讀取時先剝掉。「查無結果」(符號不存在
    或零匹配)回 `Unable to search database` 而非 0 lines 標頭,等價舊
    `-L` 模式的空輸出。stdout 用 binary 無緩衝 + select,任何 timeout/
    EOF/怪回覆都能偵測而不是永久卡死。"""

    def __init__(self, root: str) -> None:
        self.root = root
        # 生命週期跨越整個 worker,close() 收 — 不能用 with(SIM115)
        self.stderr_f = tempfile.TemporaryFile()  # noqa: SIM115
        self.proc = subprocess.Popen(
            [tool_path("cscope"), "-d", "-l", "-f", CSCOPE_DB],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr_f, bufsize=0)
        self._buf = b""

    def _readline(self) -> bytes | None:
        """讀一行(去行尾);None=timeout、b""=EOF(行程亡故)。"""
        stdout = self.proc.stdout
        assert stdout is not None
        deadline = time.monotonic() + _CSCOPE_QUERY_TIMEOUT
        while b"\n" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([stdout], [], [], min(left, 5.0))
            if not ready:
                continue
            chunk = os.read(stdout.fileno(), 65536)
            if not chunk:
                return b""
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line[:-1] if line.endswith(b"\r") else line

    def _stderr_tail(self) -> str:
        try:
            self.stderr_f.seek(0, os.SEEK_END)
            size = self.stderr_f.tell()
            self.stderr_f.seek(max(0, size - 300))
            return self.stderr_f.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""

    def query(self, qflag: str, sym: str) -> tuple[list[CscopeRow], str | None]:
        """回 (rows, None);任何協定失敗回 ([], 錯誤描述),此後這個
        worker 不可信,呼叫端必須重生。"""
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(f"{qflag}{sym}\n".encode())
            self.proc.stdin.flush()
        except OSError as e:
            return [], f"write failed ({e}); stderr: {self._stderr_tail()}"
        header = self._readline()
        if header is None:
            return [], f"query timeout ({_CSCOPE_QUERY_TIMEOUT:.0f}s)"
        if header == b"":
            return [], f"worker died (EOF); stderr: {self._stderr_tail()}"
        stripped = header.strip()
        while stripped.startswith(b">> "):   # 提示符黏連
            stripped = stripped[3:]
        if stripped == _CSCOPE_NO_RESULT:
            return [], None
        m = _CSCOPE_HEADER_RE.match(stripped)
        if not m:
            return [], (f"unexpected response {header[:120]!r}; "
                        f"stderr: {self._stderr_tail()}")
        out: list[CscopeRow] = []
        for _ in range(int(m.group(1))):
            raw = self._readline()
            if not raw:
                return [], "worker died mid-response" if raw == b"" \
                    else "timeout mid-response"
            p = raw.decode("utf-8", "replace").split(None, 3)
            if len(p) >= 3 and p[2].isdigit():
                out.append((p[1], p[0], int(p[2]), p[3] if len(p) > 3 else ""))
        return out, None

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()   # EOF → cscope 自行退出
        except OSError:
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.stderr_f.close()


_CSCOPE_TL = threading.local()            # 每執行緒一個常駐 worker
_CSCOPE_WORKERS: list[CscopeWorker] = []  # 全部 worker 的註冊表(收尾用)
_CSCOPE_WORKERS_LOCK = threading.Lock()


def _cscope_worker(root: str) -> CscopeWorker:
    w = getattr(_CSCOPE_TL, "worker", None)
    if w is None or w.root != root or w.proc.poll() is not None:
        w = CscopeWorker(root)
        _CSCOPE_TL.worker = w
        with _CSCOPE_WORKERS_LOCK:
            _CSCOPE_WORKERS.append(w)
    return w


def _retire_cscope_worker(w: CscopeWorker) -> None:
    _CSCOPE_TL.worker = None
    with _CSCOPE_WORKERS_LOCK:
        if w in _CSCOPE_WORKERS:
            _CSCOPE_WORKERS.remove(w)
    w.close()


def _close_cscope_workers() -> None:
    with _CSCOPE_WORKERS_LOCK:
        ws = list(_CSCOPE_WORKERS)
        _CSCOPE_WORKERS.clear()
    for w in ws:
        w.close()


class _CscopePool:
    """with 區塊結束時(含異常路徑)關閉所有常駐 cscope worker。"""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> None:
        _close_cscope_workers()


class CrossrefError(Exception):
    """cscope.out 直讀失敗(版本/格式不符)——呼叫端須降級逐符號查詢。"""


_XREF_ASSIGN_RE = re.compile(
    rb"^\s*(=(?!=)|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=)")

XrefMaps = tuple[dict[str, list[CscopeRow]], dict[str, list[CscopeRow]],
                 dict[str, list[CscopeRow]], dict[str, list[CscopeRow]]]


def _iter_crossref_lines(fh: Any, chunk_size: int = 1 << 26) -> Any:
    """64MB chunk + 殘尾接續的行迭代器(不含行尾 \\n)。
    與整檔 split(b"\\n") 逐行等價,但峰值記憶體 = 一個 chunk。"""
    carry = b""
    while True:
        chunk = fh.read(chunk_size)
        if not chunk:
            if carry:
                yield carry
            return
        parts = (carry + chunk).split(b"\n")
        carry = parts.pop()
        yield from parts


def parse_cscope_crossref(db_path: str, want_calls: set[str],
                          want_refs: set[str]) -> XrefMaps:
    """D17 Day2:單遍解析 cscope -c(未壓縮)crossref,一次取得「所有」
    符號的查詢結果,取代逐符號 `cscope -dL<q>` 呼叫(kernel 級 ~40 萬次
    x 每次線性重掃整個 crossref → 一次 O(檔案大小) 掃描)。

    回 (calls, refs, assigns, includes_by_basename),各 map 的 row 形狀
    與 -L 輸出解析結果一字不差:(scope, file, line, text)。calls 只收
    want_calls(函式+巨集名)、refs/assigns 只收 want_refs(全域名),
    界定記憶體上限(kernel 全部符號的 refs 是千萬級)。

    格式(cscope 15,-c;逐條由 15.9 實測逆向,tests 有對拍):
    `\\t@file` 分檔;`<lineno> text0` 起行記錄,之後符號行/文字片段
    嚴格交錯(符號位置遇空行=記錄終止;行尾恰為符號時會有空文字片段);
    `\\t$fn` 函式定義、`\\t#macro` 巨集定義、`\\t}`/`\\t)` 對應結束、
    `` \\t` `` 呼叫、`\\t~"`/`\\t~<` include、字母標記=各類定義、
    無標記=一般引用;行文字 = 片段+符號名依序串接。

    scope 引擎(cscope 查詢端行為的等價重建;它自己的 -L 查詢在多行
    定義/大檔上反而有丟行與雙報 bug,見 D17 記錄):
    - func 由 $ 設定、} 清除;macro 由 # 設定、) 清除(巢於函式內的
      #define 結束後恢復函式 scope);cur = macro ?? func。
    - 發射:cur≠<global> → cur;字母定義標記 → <global>;否則同名符號
      上次發射的 scope(黏滯 fallback;@file 清空;巨集區發射不進黏滯)。
    - $ 先切換再發射;# 先發射再切換。
    - -L9 等價:符號「存入 crossref 的出現位置」後方文字片段以賦值運算子
      開頭(== 不算、++/-- 不算;每行只看第一次出現——cscope 亦然)。
    - 同名同行去重:refs/calls 取第一個 entry,assigns 任一 entry 通過。

    記憶體:按 64MB chunk 串流(kernel 全樹的 -c crossref ~1.2GB,整檔
    split 進 list 會在 8GB 機器上爆);峰值 = 一個 chunk + 進行中的 maps。
    """
    fh = open(db_path, "rb")  # noqa: SIM115 — 生命週期跨 generator,下方 with 收
    with fh:
        header = fh.readline().decode("utf-8", "replace").rstrip("\n")
        if not header.startswith("cscope 15 ") or " -c " not in header:
            raise CrossrefError(f"非 cscope 15 -c 格式:{header[:60]!r}")

        calls: dict[str, list[CscopeRow]] = {}
        refs: dict[str, list[CscopeRow]] = {}
        assigns: dict[str, list[CscopeRow]] = {}
        includes: dict[str, list[CscopeRow]] = {}  # basename(寫入路徑)→rows

        cur_file = ""
        func = "<global>"
        shadows: list[str] = []  # 嵌套 $ 時被遮蔽的外層 func(雙發射候選)
        macro: str | None = None
        sticky: dict[str, str] = {}
        it = _iter_crossref_lines(fh)
        saw_trailer = False
        for ln in it:
            if ln.startswith(b"\t@"):
                fname = ln[2:]
                if not fname:                 # trailer:解析結束
                    saw_trailer = True
                    break
                cur_file = fname.decode("utf-8", "replace")
                func, shadows, macro, sticky = "<global>", [], None, {}
                continue
            if ln[:1].isdigit():              # 行記錄
                sp = ln.find(b" ")
                lineno = int(ln[:sp])
                frags = [ln[sp + 1:]]
                entries: list[tuple[bytes, bytes, int]] = []
                expect_sym = True
                for cur in it:
                    if expect_sym:
                        if cur == b"":        # 符號位置空行=終止(已消耗)
                            break
                        if cur.startswith(b"\t"):
                            entries.append((cur[1:2], cur[2:], len(frags)))
                        else:
                            entries.append((b"", cur, len(frags)))
                    else:
                        frags.append(cur)
                    expect_sym = not expect_sym
                text: str | None = None       # 懶重建(多數行沒人要)
                rec_seen: set[tuple[str, str, str]] = set()
                for mark, bname, fidx in entries:
                    if mark == b")":
                        macro = None
                        continue
                    if mark == b"}":
                        func = "<global>"
                        shadows = []
                        continue
                    if not bname:
                        continue
                    nm = bname.decode("utf-8", "replace")
                    if mark == b"$":
                        # 嵌套 $(前一函式沒有 } 就出現新 $)= 掃描器的假
                        # 標記:C++ 建構子初始化列表(`: wpagui(_wpagui)`)
                        # 產生假內層,巨集生成函式的頂層呼叫
                        # (`BIT_SH(bit_rol, brol)`)產生假外層——哪個是真
                        # caller 掃描層無從判定。解法:外層進 shadows,之後
                        # 每站點對全部候選「雙發射」,交給 attribute_src 以
                        # 節點存在+行區間仲裁(重現 cscope 查詢端雙報+舊
                        # 管線過濾的實際行為;wpa/redis 邊差分實證此路徑
                        # 損失最小)。
                        if func != "<global>" and func != nm \
                                and func not in shadows:
                            shadows.append(func)
                        func = nm
                        macro = None
                    want_inc = mark == b"~"
                    want_c = mark == b"`" and nm in want_calls
                    want_r = not want_inc and nm in want_refs
                    if not (want_inc or want_c or want_r):
                        # 黏滯只在同名符號自己發射時被讀,無關名字不必簿記
                        if mark == b"#":
                            macro = nm
                        continue
                    if text is None:
                        parts: list[bytes] = []
                        fi = 0
                        for _m2, nm2, fx2 in entries:
                            parts.extend(frags[fi:fx2])
                            fi = fx2
                            parts.append(nm2)
                        parts.extend(frags[fi:])
                        text = b"".join(parts).decode("utf-8", "replace")
                    if want_inc:
                        base = nm[1:].rsplit("/", 1)[-1]  # nm=引號字元+路徑
                        includes.setdefault(base, []).append(
                            ("<global>", cur_file, lineno, text))
                        continue
                    cur_scope = macro if macro is not None else func
                    if cur_scope != "<global>":
                        emits = [cur_scope] + \
                            [s for s in shadows if macro is None]
                    elif mark and mark.isalpha():
                        emits = ["<global>"]
                    else:
                        emits = [sticky.get(nm, "<global>")]
                    if macro is None:
                        sticky[nm] = emits[0]
                    is_assign = (fidx < len(frags)
                                 and _XREF_ASSIGN_RE.match(frags[fidx]))
                    for emit in emits:
                        row: CscopeRow = (emit, cur_file, lineno, text)
                        if want_r and ("r", nm, emit) not in rec_seen:
                            rec_seen.add(("r", nm, emit))
                            refs.setdefault(nm, []).append(row)
                        if want_c and ("c", nm, emit) not in rec_seen:
                            rec_seen.add(("c", nm, emit))
                            calls.setdefault(nm, []).append(row)
                        if (want_r and is_assign
                                and ("a", nm, emit) not in rec_seen):
                            rec_seen.add(("a", nm, emit))
                            assigns.setdefault(nm, []).append(row)
                    if mark == b"#":
                        macro = nm
                continue
            if ln.startswith(b"\t"):          # 記錄外裸標記(多行 #define 的 ))
                mark, bnm = ln[1:2], ln[2:]
                if mark == b")":
                    macro = None
                elif mark == b"}":
                    func = "<global>"
                    shadows = []
                elif mark == b"$" and bnm:
                    bare_fn = bnm.decode("utf-8", "replace")
                    if func != "<global>" and func != bare_fn \
                            and func not in shadows:
                        shadows.append(func)
                    func = bare_fn
                    macro = None
                elif mark == b"#" and bnm:
                    macro = bnm.decode("utf-8", "replace")
                continue
        if not saw_trailer:
            raise CrossrefError("crossref 無 trailer(檔案截斷?)")
    return calls, refs, assigns, includes


def cscope_lines(root: str, qflag: str, sym: str) -> list[CscopeRow]:
    """cscope 查詢 sym → [(field2, file, line, text)],走常駐行程池。

    D17(2026-07-11,v5 kernel 子樹索引 3h15m 後拍板):原本每符號
    spawn 一個 `cscope -dL<q>` 行程——kernel 級 ~40 萬次 fork/exec、
    每次重掃 44MB 索引,sys 時間(58,578s)是 user(20,674s)的 2.8 倍,
    行程開銷才是大頭。改為每執行緒一個 line-mode 常駐行程(索引載入
    一次),輸出格式與 -L 相同,parser 不變,只換傳輸層。

    D15 語意保留(2026-07-06,redis/jemalloc 巨集內部錯誤):單一符號
    失敗不該讓整個 build 陣亡。任何協定失敗先重生 worker 重試一次
    (保護「前一個符號毒死行程、這個符號無辜」;毒符號 100% 重現,
    重試必然再失敗),再失敗才記入 CSCOPE_SKIPPED 跳過該符號。"""
    err = ""
    for _attempt in (1, 2):
        w = _cscope_worker(root)
        rows, qerr = w.query(qflag, sym)
        if qerr is None:
            return rows
        err = qerr
        _retire_cscope_worker(w)
    CSCOPE_SKIPPED.append((sym, err[:200]))
    return []


def ctags_defs(root: str) -> list[Def]:
    """L0:ctags JSON → 節點原料。kind: function|global(ctags f/v);
    static 用定義行文字偵測(近似,documented)。"""
    out = run_checked([tool_path("ctags"), "-R", "--languages=C,C++",
                       "--kinds-C=f,v,d", "--kinds-C++=f,v,d",
                       "--fields=+neS", "--output-format=json", "."], root)
    src_cache: dict[str, list[str]] = {}
    defs: list[Def] = []
    for raw in out.splitlines():
        try:
            o = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if o.get("_type") != "tag":
            continue
        path = os.path.normpath(o["path"])
        line = int(o.get("line", 0))
        if path not in src_cache:
            try:
                with open(os.path.join(root, path), errors="replace") as f:
                    src_cache[path] = f.read().splitlines()
            except OSError:
                src_cache[path] = []
        kind = {"function": "function", "variable": "global",
                "macro": "macro"}.get(o.get("kind", ""))
        if not kind:
            continue
        defs.append({
            "name": o["name"], "kind": kind, "file": path,
            "line_start": line, "line_end": int(o.get("end", line)),
            "is_static": detect_static(src_cache[path], line),
            "signature": o.get("signature"),
        })
    return defs


def source_files(root: str) -> list[str]:
    exts = (".c", ".h", ".cc", ".cpp", ".hpp")
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        out.extend(os.path.relpath(os.path.join(dirpath, fn), root)
                   for fn in filenames if fn.endswith(exts))
    return sorted(out)


def git_head(root: str) -> str | None:
    try:
        r = subprocess.run([tool_path("git"), "-C", root, "rev-parse", "HEAD"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_co_change_groups(root: str, known: set[str],
                         window: int = 500) -> list[list[str]]:
    try:
        r = subprocess.run(
            [tool_path("git"), "-C", root, "log", "--name-only",
             "--pretty=format:%H", "-n", str(window)],
            capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    groups: list[list[str]] = []
    cur: list[str] = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r"[0-9a-f]{40}", line):
            if cur:
                groups.append(cur)
            cur = []
        elif line in known:
            cur.append(line)
    if cur:
        groups.append(cur)
    return groups


# ---------------------------------------------------------------- build

AddEdge = Any   # callable(src_id, dst_id, kind, file, line, origin, meta) -> None


def _enclosing(by_file: dict[str, list[Def]], file: str, line: int) -> Def | None:
    for d in by_file.get(file, []):
        if d["line_start"] <= line <= d["line_end"]:
            return d
    return None


def scan_l3(root: str, srcs: list[str], defs: list[Def],
            fn_index: dict[str, list[Def]], add_edge: AddEdge,
            manual_regs: dict[str, list[tuple[int, str | None]]]) -> tuple[int, int, int]:
    """L3:callback(fn-as-arg)+ fnptr(field-keyed 註冊→分派)。單遍全檔文字掃描,
    字串/註解先剝除(string_fake_call 防線)。回傳 (callback 邊數, fnptr 邊數)。"""
    by_file: dict[str, list[Def]] = {}
    for d in defs:
        if d["kind"] == "function":
            by_file.setdefault(d["file"], []).append(d)
    fn_names = set(fn_index)
    regs: dict[str, set[int]] = {}
    dispatch_sites: list[tuple[str, int, str, Def]] = []
    n_cb = n_fp = n_mreg = 0

    for path in srcs:
        try:
            with open(os.path.join(root, path), errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        in_block = False
        for lineno, raw in enumerate(text.splitlines(), 1):
            clean, in_block = strip_c_line(raw, in_block)
            for field, fname in REG_RE.findall(clean):
                if fname in fn_names:
                    for dst in choose_dst(fn_index[fname], path):
                        regs.setdefault(field, set()).add(int(dst["id"]))
            for field in DISPATCH_RE.findall(clean):
                src = _enclosing(by_file, path, lineno)
                if src:
                    dispatch_sites.append((path, lineno, field, src))
            for nm in callback_hits(clean, fn_names):
                src = _enclosing(by_file, path, lineno)
                if not src or src["name"] == nm:
                    continue
                viable = choose_dst(fn_index[nm], path)
                meta = edge_meta(len(viable), {"heur": "fn-as-arg"})
                for dst in viable:
                    if dst["id"] != src["id"]:
                        add_edge(src["id"], dst["id"], "callback", path, lineno,
                                 "callback", meta)
                        n_cb += 1
    for path, lineno, field, src in dispatch_sites:
        ids = regs.get(field, set())
        if 0 < len(ids) <= FANOUT_CAP:
            meta = json.dumps({"field": field, "handlers": len(ids)},
                              sort_keys=True)
            for did in ids:
                if did != src["id"]:
                    add_edge(src["id"], did, "fnptr", path, lineno, "fnptr", meta)
                    n_fp += 1
        # 使用者 registrations(FR3):asserted_by_user,不受 FANOUT_CAP 限制
        for did, struct in manual_regs.get(field, []):
            if did != src["id"]:
                m: dict[str, Any] = {"manual": True, "field": field}
                if struct:
                    m["struct"] = struct
                add_edge(src["id"], did, "fnptr", path, lineno, "manual",
                         json.dumps(m, sort_keys=True))
                n_mreg += 1
    return n_cb, n_fp, n_mreg


def load_manual(root: str) -> tuple[list[dict[str, str]], list[dict[str, str]], str | None]:
    """讀 fnptr.json(FR3,ccq.fnptr.json 血統)→ (links, registrations, sha256)。
    格式錯誤大聲死(P7)。registrations 需 field+handler(struct 選填);
    links 需 src+dst。sha256 存進 meta 供 stale 偵測(manual = asserted_by_user,
    來源變更後圖裡的 manual 邊即過期)。"""
    p = os.path.join(root, "fnptr.json")
    if not os.path.exists(p):
        return [], [], None
    with open(p, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: fnptr.json invalid JSON: {e}")
    links: list[dict[str, str]] = []
    for entry in data.get("links", []):
        if not ("src" in entry and "dst" in entry):
            sys.exit(f"ERROR: fnptr.json link needs src+dst: {entry}")
        links.append(entry)
    regs: list[dict[str, str]] = []
    for entry in data.get("registrations", []):
        if not ("field" in entry and "handler" in entry):
            sys.exit(f"ERROR: fnptr.json registration needs field+handler: {entry}")
        regs.append(entry)
    return links, regs, digest


def make_resolver(con: sqlite3.Connection, defs: list[Def],
                  fn_index: dict[str, list[Def]]) -> Any:
    """符號名 → node id:qname 精確 → 唯一 name → placeholder(manual 端點
    缺定義時建佔位節點——鐵律:使用者斷言永遠保留)。"""
    by_qname = {d["qname"]: d for d in defs}

    def resolve(sym: str) -> int:
        if sym in by_qname:
            return int(by_qname[sym]["id"])
        cands = fn_index.get(sym, [])
        if len(cands) == 1:
            return int(cands[0]["id"])
        rowid = con.execute(
            "INSERT OR IGNORE INTO nodes (name,qname,kind,file,line_start,"
            "line_end,is_static,origin,confidence) "
            "VALUES (?,?, 'function', '(manual)', 0, 0, 0, 'manual', 1.0)",
            (sym, sym)).lastrowid
        if rowid:
            return int(rowid)
        return int(con.execute("SELECT id FROM nodes WHERE qname=? AND "
                               "kind='function'", (sym,)).fetchone()[0])

    return resolve


def build(root: str, db_path: str, jobs: int,
          incremental: bool = False, module_map: str | None = None) -> None:
    require_universal_ctags()          # R2:flavor 偵測,非 Universal 大聲死
    try:
        subprocess.run([tool_path("cscope"), "--version"], capture_output=True)
    except FileNotFoundError:
        sys.exit(f"ERROR: cscope not found({tool_path('cscope')})— L1 需要它。"
                 "macOS: brew install cscope / Linux: apt install cscope;"
                 "或設 CCODEGRAPH_CSCOPE_PATH=/path/to/cscope")
    t0 = time.time()
    CSCOPE_SKIPPED.clear()   # D15:每次 build() 重新計數,不跨呼叫累積
    pdir = os.path.join(root, PRODUCTS_DIR)
    os.makedirs(pdir, exist_ok=True)
    legacy = os.path.join(root, ".ideal-graph.cscope.out")
    if os.path.exists(legacy):          # 改名遷移(一次性)
        os.remove(legacy)
        print(f"removed legacy {legacy}")
    gi = os.path.join(pdir, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as fh:
            fh.write("*\n")           # 產物永不進使用者的版控(ccq 經驗)

    srcs = source_files(root)
    hashes = {p: file_hash(os.path.join(root, p)) for p in srcs}
    kept_edges: list[tuple[Any, ...]] = []
    affected: set[str] = set()
    touched: set[str] = set()
    deleted: set[str] = set()
    aff_headers: set[str] = set()
    if incremental and not os.path.exists(db_path):
        print("(no existing graph — falling back to full build)")
        incremental = False
    if incremental:
        oldcon = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        old_hashes = dict(oldcon.execute(
            "SELECT path, content_hash FROM files WHERE content_hash "
            "IS NOT NULL"))
        changed, added, deleted = compute_changes(old_hashes, hashes)
        touched = changed | added
        if not (touched or deleted):
            print("up to date — nothing changed (hash-identical)")
            return
        print(f"[L5] incremental: changed={len(changed)} added={len(added)} "
              f"deleted={len(deleted)}")
        # 受影響符號 = 變更/刪除檔的舊定義名 + 變更檔文字中出現的識別字
        #(後者涵蓋「不變檔對變更檔符號」與「變更檔內的呼叫站點」兩個方向)
        ph = ",".join("?" * len(touched | deleted))
        def_changed: set[str] = set()
        for (nm,) in oldcon.execute(
                f"SELECT DISTINCT name FROM nodes WHERE kind != 'file' "
                f"AND file IN ({ph})", tuple(touched | deleted)):
            def_changed.add(nm)
        oldcon.close()
        idents: set[str] = set()
        specs: set[str] = set()
        for p in touched:
            try:
                with open(os.path.join(root, p), errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            idents.update(IDENT_RE.findall(text))
            specs.update(INCLUDE_RE.findall(text))
        aff_headers = {h for h in srcs if h.endswith(HEADER_EXTS)
                       and (h in touched or h in deleted
                            or any(include_matches(sp, h) for sp in specs))}

    mm_rules = load_module_map(module_map) if module_map else []
    print("[L0] cscope index + ctags 節點 …")
    # D17 註:實驗過 -q 倒排索引(單查詢 9.5ms→0.15ms),但 cscope 的
    # 倒排路徑與線性掃描路徑回「不同的結果集」——wpa 實測丟 534 calls +
    # 1000 includes 真邊(也多撿 2224 真邊,雙向皆真)。零回歸紅線斃掉。
    # -c:存未壓縮 crossref 供 parse_cscope_crossref 直讀(D17 Day2);
    # 只影響編碼不影響內容,cscope 自身查詢兩種都吃(降級路徑不受影響)。
    cscope_flags = "-bckRu" if (incremental and (touched or deleted)) \
        else "-bckR"  # -u:增量時無條件重建(cscope 吃 mtime 秒級精度,快改看不見)
    run_checked([tool_path("cscope"), cscope_flags, "-f", CSCOPE_DB], root)
    defs = assign_qnames(ctags_defs(root))
    if incremental:
        # 定義真的變了的名字:舊圖在 touched|deleted 的定義 + 新解析在 touched 的定義
        def_changed.update(d["name"] for d in defs if d["file"] in touched)
        all_names = {d["name"] for d in defs}
        # 重掃集 = touched 檔的識別字 ∩ 已知名(涵蓋站點被踢的邊)+ def_changed
        affected = (idents & all_names) | def_changed
        # 搬運:踢除條件收窄到「站點在 touched/deleted」或「端點定義變更」;
        # 因 src 定義變更被踢的邊,其 dst 名補進重掃集(否則 dst 不受影響的
        # 邊會永久丟失——wpa data→addEvent 類,136 邊漂移的根因)
        oldcon2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for row in oldcon2.execute(
                "SELECT n1.qname, n1.kind, n1.name, "
                "n2.qname, n2.kind, n2.name, e.kind, "
                "e.file, e.line, e.origin, e.confidence, e.meta "
                "FROM edges e JOIN nodes n1 ON n1.id=e.src "
                "JOIN nodes n2 ON n2.id=e.dst "
                "WHERE e.origin IN ('cscope', 'clink')"):
            _sq, _sk, sn, _dq, _dk, dn, _k, ef, _ln, _o, _c, _m = row
            if ef in touched or ef in deleted:
                continue
            if sn in def_changed:
                affected.add(dn)
                continue
            if dn in def_changed:
                continue
            kept_edges.append(row)
        oldcon2.close()
    n_fn = sum(1 for d in defs if d["kind"] == "function")
    n_gv = sum(1 for d in defs if d["kind"] == "global")
    n_mc = sum(1 for d in defs if d["kind"] == "macro")
    print(f"     {n_fn} functions, {n_gv} globals, {n_mc} macros, "
          f"{len(srcs)} files")

    # history 繼承:append-only 寫入日誌跨重建保留(Q1b)
    old_history: list[dict[str, Any]] = []
    if os.path.exists(db_path):
        try:
            oc = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            hrow = oc.execute(
                "SELECT value FROM meta WHERE key='history'").fetchone()
            if hrow:
                old_history = json.loads(hrow[0])
            oc.close()
        except sqlite3.Error:
            pass

    # 原子性重建(codex 高風險 1):寫 temp,成功才 os.replace
    tmp_db = db_path + ".building"
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    con = sqlite3.connect(tmp_db)
    # B3:寫進 temp 檔、成功才 os.replace——中途崩潰 = 丟棄 temp,
    # 所以 journal/synchronous 可以整段關掉;次要索引 bulk load 後才建。
    con.executescript(
        "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
        "PRAGMA cache_size=-262144; PRAGMA temp_store=MEMORY;")
    con.executescript(SCHEMA_BASE_SQL)
    head = git_head(root)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    con.executemany(
        "INSERT INTO files (path, lang, content_hash, indexed_at, git_rev) "
        "VALUES (?,?,?,?,?)",
        [(p, "c", hashes[p], now, head) for p in srcs])
    for d in defs:
        d["id"] = con.execute(
            "INSERT INTO nodes (name,qname,kind,file,line_start,line_end,"
            "signature,is_static,module,origin,confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d["qname"], d["kind"], d["file"], d["line_start"],
             d["line_end"], d.get("signature"), int(d["is_static"]),
             module_of(mm_rules, str(d["file"])), "ctags",
             CONFIDENCE["ctags"])).lastrowid
    file_ids: dict[str, int] = {}
    for p in srcs:
        rowid = con.execute(
            "INSERT INTO nodes (name,qname,kind,file,line_start,line_end,"
            "is_static,module,origin,confidence) "
            "VALUES (?,?,?,?,?,?,0,?,'ctags',1.0)",
            (os.path.basename(p), p, "file", p, 1, 1,
             module_of(mm_rules, p))).lastrowid
        assert rowid is not None
        file_ids[p] = rowid

    fn_index: dict[str, list[Def]] = {}
    gv_index: dict[str, list[Def]] = {}
    mc_index: dict[str, list[Def]] = {}
    for d in defs:
        idx = {"function": fn_index, "global": gv_index,
               "macro": mc_index}[str(d["kind"])]
        idx.setdefault(d["name"], []).append(d)

    # B3:邊插入批次緩衝——全樹 54.8M 條逐列 execute 的 Python/SQLite
    # 語句開銷是分鐘級;executemany 分批沖洗。INSERT OR IGNORE 的去重
    # 語意不受順序影響(重複列內容完全相同)。
    edge_buf: list[tuple[Any, ...]] = []

    def flush_edges() -> None:
        if edge_buf:
            con.executemany(
                "INSERT OR IGNORE INTO edges (src,dst,kind,file,line,origin,"
                "confidence,meta) VALUES (?,?,?,?,?,?,?,?)", edge_buf)
            edge_buf.clear()

    def add_edge(src_id: int, dst_id: int, kind: str, file: str | None,
                 line: int | None, origin: str, meta: str = "{}") -> None:
        edge_buf.append((src_id, dst_id, kind, file, line, origin,
                         CONFIDENCE[origin], meta))
        if len(edge_buf) >= 100_000:
            flush_edges()

    if incremental:
        # 鍵必須含 kind:qname 跨 kind 可撞名(wpa_printf 同時是 function
        # 與 macro 節點,UNIQUE(qname,kind) 允許)——單以 qname 對映會把
        # 函式 dst 的 kept 邊錯接到 macro 節點(wpa 實測 +12,577 條污染)。
        qid = {(q, kd): i for q, kd, i in con.execute(
            "SELECT qname, kind, id FROM nodes")}
        n_kept = 0
        for sq, sk, _sn, dq, dk, _dn, k, ef, ln, o, c, m in kept_edges:
            si, di = qid.get((sq, sk)), qid.get((dq, dk))
            if si is not None and di is not None:
                con.execute(
                    "INSERT OR IGNORE INTO edges (src,dst,kind,file,line,"
                    "origin,confidence,meta) VALUES (?,?,?,?,?,?,?,?)",
                    (si, di, k, ef, ln, o, c, m))
                n_kept += 1
        print(f"[L5] kept {n_kept} edges; resweep {len(affected)} "
              f"affected names")

    def sweep_names(index: dict[str, list[Def]]) -> list[str]:
        if incremental:
            return sorted(set(index) & affected)
        return sorted(index)

    fn_names = sweep_names(fn_index)
    gv_names = sweep_names(gv_index)
    # D17 Day2:先試 crossref 直讀(一次掃描取得全部查詢結果);失敗則
    # 大聲降級為逐符號 cscope 常駐行程查詢(P7:不靜默,結果等價但慢)。
    xref: XrefMaps | None = None
    try:
        xref = parse_cscope_crossref(
            os.path.join(root, CSCOPE_DB),
            want_calls=set(fn_index) | set(mc_index),
            want_refs=set(gv_index))
    except (CrossrefError, OSError, MemoryError) as e:
        print(f"WARNING: cscope crossref 直讀失敗({e})——降級為"
              "逐符號 cscope 查詢(慢,結果等價)")
    print(f"[L1] cscope 邊:calls x{len(fn_names)} + "
          f"reads/writes x{len(gv_names)} + includes"
          f"({'crossref 直讀' if xref else f'{jobs} workers'})…")
    all_headers = [p for p in srcs if p.endswith(HEADER_EXTS)]
    base_count: dict[str, int] = {}
    for h in all_headers:
        base_count[os.path.basename(h)] = base_count.get(os.path.basename(h), 0) + 1
    headers = sorted(aff_headers) if incremental else all_headers
    with _CscopePool(), cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        def qmap(qflag: str, names: list[str],
                 xmap: dict[str, list[CscopeRow]] | None
                 ) -> Any:
            """xref 查表;無 xref 時逐符號查詢(執行緒池+常駐行程)。"""
            if xref is not None:
                assert xmap is not None
                return (xmap.get(n, []) for n in names)
            return ex.map(lambda n: cscope_lines(root, qflag, n), names)

        xc, xr, xa, xi = xref if xref is not None else (None,) * 4
        # calls:對每個函式名問「誰呼叫它」(-dL3;-dL2 會漏巢狀內層呼叫)
        callers_of = qmap("3", fn_names, xc)
        for name, rows in zip(fn_names, callers_of, strict=True):
            for caller, f, ln, _txt in rows:
                if caller in ("<global>", "<unknown>"):
                    continue
                src = attribute_src(fn_index, caller, f, ln)
                if not src:
                    continue
                viable = choose_dst(fn_index[name], f)
                meta = edge_meta(len(viable))
                for dst in viable:
                    if dst["id"] != src["id"]:
                        add_edge(src["id"], dst["id"], "calls", f, ln,
                                 "cscope", meta)
        # reads/writes:reads = L0 站點 - L9 站點;write 站點若同時讀
        # (x++ / x+=1 / x=x+1)補一條 reads(meta.rmw,codex 高風險 5)
        refs_of = qmap("0", gv_names, xr)
        writes_of = qmap("9", gv_names, xa)
        for name, refs, writes in zip(gv_names, refs_of, writes_of, strict=True):
            wsites = {(f, ln) for _fn, f, ln, _t in writes}
            for kind, rows in (("writes", writes), ("reads", refs)):
                for fn, f, ln, txt in rows:
                    if fn in ("<global>", "<unknown>"):
                        continue
                    if kind == "reads" and (f, ln) in wsites:
                        continue
                    src = attribute_src(fn_index, fn, f, ln)
                    if not src:
                        continue
                    viable = choose_dst(gv_index[name], f)
                    meta = edge_meta(len(viable))
                    for dst in viable:
                        add_edge(src["id"], dst["id"], kind, f, ln,
                                 "cscope", meta)
                    # RMW 對稱補償(codex 高風險 5):write 站點同時讀 →
                    # 補 reads;read 站點其實在改(counter++,cscope -L9
                    # 不視為 assignment)→ 補 writes。皆標 meta.rmw。
                    if is_rmw(txt, name):
                        other_kind = "reads" if kind == "writes" else "writes"
                        rmeta = edge_meta(len(viable), {"rmw": True})
                        for dst in viable:
                            add_edge(src["id"], dst["id"], other_kind, f, ln,
                                     "cscope", rmeta)
        # expands:函式 → 函式型巨集(L2';cscope 把巨集使用當呼叫報,
        # -dL3 <macro> 的歸戶與 calls 相同)。D11:tree-sitter 層除役後
        # 真正的缺口是這個維度(wpa 實測 586 個被呼叫的巨集)。
        mc_names = sweep_names(mc_index)
        users_of = qmap("3", mc_names, xc)
        for name, rows in zip(mc_names, users_of, strict=True):
            for user, f, ln, _txt in rows:
                if user in ("<global>", "<unknown>"):
                    continue
                src = attribute_src(fn_index, user, f, ln)
                if not src:
                    continue
                viable = choose_dst(mc_index[name], f)
                meta = edge_meta(len(viable))
                for dst in viable:
                    add_edge(src["id"], dst["id"], "expands", f, ln,
                             "cscope", meta)
        # includes:file → file;#include 內容與 header 路徑比對
        # (重名 header 防錯連,codex 高風險 4)
        includers = (
            (xi.get(os.path.basename(h), []) for h in headers)
            if xi is not None else ex.map(
                lambda h: cscope_lines(root, "8", os.path.basename(h)),
                headers))
        for hdr, rows in zip(headers, includers, strict=True):
            for _f2, f, ln, txt in rows:
                if f not in file_ids or f == hdr:
                    continue
                m = INCLUDE_RE.search(txt)
                if m and not include_matches(m.group(1), hdr):
                    continue
                amb = (m and "/" not in m.group(1)
                       and base_count[os.path.basename(hdr)] > 1)
                meta = (json.dumps({"ambiguous": True, "rule": "dup-basename"})
                        if amb else "{}")
                add_edge(file_ids[f], file_ids[hdr], "includes", f, ln,
                         "cscope", meta)

    print("[L3] callback + fnptr 啟發式 + manual 表 …")
    mlinks, mregs, mhash = load_manual(root)
    resolve = make_resolver(con, defs, fn_index)
    manual_regs: dict[str, list[tuple[int, str | None]]] = {}
    for r in mregs:
        manual_regs.setdefault(r["field"], []).append(
            (resolve(r["handler"]), r.get("struct")))
    n_cb, n_fp, n_mreg = scan_l3(root, srcs, defs, fn_index, add_edge,
                                 manual_regs)
    n_ml = 0
    for link in mlinks:
        add_edge(resolve(link["src"]), resolve(link["dst"]), "fnptr",
                 "(manual)", 0, "manual", '{"manual": true}')
        n_ml += 1
    if mhash:
        con.execute("INSERT INTO meta VALUES ('manual_src_hash',?)", (mhash,))
    print(f"     callback={n_cb}, fnptr={n_fp}, "
          f"manual: registrations={n_mreg}, links={n_ml}")

    # L5 後半:git 共變邊(退化矩陣:非 git repo → 明講跳過)
    groups = git_co_change_groups(root, set(srcs))
    if groups:
        pairs = co_change_groups_to_pairs(groups)
        for a, b, cnt2 in pairs:
            ia, ib = file_ids.get(a), file_ids.get(b)
            if ia and ib:
                add_edge(ia, ib, "co_changes", None, None, "git",
                         json.dumps({"count": cnt2, "window": 500}))
        print(f"[L5] co_changes: {len(pairs)} pairs(git log 500 commits)")
    else:
        print("[L5] co_changes skipped — not a git repo(或 git 不可用)")

    con.execute("INSERT INTO meta VALUES ('schema_version','2')")
    con.execute("INSERT INTO meta VALUES ('db_label',?)",
                (os.path.basename(db_path),))
    old_history.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "action": "build-incremental" if incremental else "build-full",
        "files": len(srcs), "git": (head[:12] if head else None),
        "module_map": os.path.basename(module_map) if module_map else None,
        "cscope_skipped": len(CSCOPE_SKIPPED),
        "seconds": round(time.time() - t0, 1)})
    flush_edges()
    con.executescript(SCHEMA_INDEXES_SQL)   # B3:次要索引 bulk load 後建
    con.execute("INSERT INTO meta VALUES ('history',?)",
                (json.dumps(old_history, ensure_ascii=False),))
    con.execute("INSERT INTO meta VALUES ('root',?)", (root,))
    con.execute("INSERT INTO meta VALUES ('engines_run',?)",
                (json.dumps([{"engine": "ctags+cscope+heuristics",
                              "layers": "L0+L1+L3+L5",
                              "mode": (f"incremental({len(touched)} touched, "
                                       f"{len(deleted)} deleted)"
                                       if incremental else "full"),
                              "seconds": round(time.time() - t0, 1)}]),))
    con.commit()
    counts = dict(con.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind"))
    con.close()
    os.replace(tmp_db, db_path)          # 原子切換
    print(f"done: {db_path}  ({len(defs) + len(srcs)} nodes; edges: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f"; {time.time() - t0:.0f}s)")
    if CSCOPE_SKIPPED:
        print(f"WARNING: cscope 對 {len(CSCOPE_SKIPPED)} 個符號回報內部錯誤"
              f"(通常是同檔內被極端密集使用的巨集/符號,如 vendored 第三方碼)"
              f"——這些符號的邊已跳過,其餘正常。範例:"
              + ", ".join(s for s, _ in CSCOPE_SKIPPED[:5])
              + (" …" if len(CSCOPE_SKIPPED) > 5 else ""))
    print("note: 語意層跑 `clink-import`(選配)可疊加 semantic 註記。")


# ------------------------------------------------- compile DB:合併與合成

def merge_compile_dbs(paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """檔案層級合併(D12):多 target build 會有多份 compile_commands.json,
    同一檔可能在不同 DB 有不同編譯規則。規則:
    - 參數順序 = 優先權;同檔取第一個提到它的 DB 的規則(first wins)
    - 只出現在後面 DB 的檔案照樣收(聯集——每個 target 獨有的檔都拿到自己的規則)
    - 規則真的不同才記 conflict(逐筆回報,P7 不靜默)"""
    merged: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    conflicts: list[str] = []
    for p in paths:
        try:
            with open(p) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"ERROR: compile DB {p} unreadable: {e}")
        if not isinstance(data, list):
            sys.exit(f"ERROR: compile DB {p} is not a JSON array")
        for entry in data:
            key = os.path.normpath(
                os.path.join(entry.get("directory", "."), entry["file"]))
            rule = entry.get("arguments") or entry.get("command")
            if key in merged:
                prev = merged[key].get("arguments") or merged[key].get("command")
                if rule != prev:
                    conflicts.append(f"{key}: {owners[key]} wins over {p}")
            else:
                merged[key] = entry
                owners[key] = p
    return list(merged.values()), conflicts


def synthesize_compile_db(root: str, srcs: list[str]) -> list[dict[str, Any]]:
    root = os.path.realpath(root)   # macOS /var↔/private/var:與 clink 的 realpath 視角對齊
    """no-build 合成 DB(ccq 血統,D13):每個編譯單元一條,-I 蓋所有含 header
    的目錄(include 命中率最大化;重名 header 依 -I 順序取捨,documented
    approximation)。刻意不給 -D:猜不出 config,亂給比不給糟。
    C 給 -xc/gnu11,C++ 給 -xc++/gnu++17(W3:C++ 資訊不漏)。"""
    inc_dirs = sorted({os.path.dirname(p) for p in srcs
                       if p.endswith(HEADER_EXTS) and os.path.dirname(p)})
    incs = [f"-I{d}" for d in inc_dirs]
    out: list[dict[str, Any]] = []
    for p in srcs:
        if p.endswith(".c"):
            lang = ["cc", "-xc", "-std=gnu11"]
        elif p.endswith((".cc", ".cpp")):
            lang = ["c++", "-xc++", "-std=gnu++17"]
        else:
            continue
        out.append({"directory": root, "file": os.path.join(root, p),
                    "arguments": [*lang, *incs, os.path.join(root, p)]})
    return out


# ---------------------------------------------------------------- R7a: clink 匯入

CLINK_BIN = os.environ.get("CCODEGRAPH_CLINK_PATH",
                           os.environ.get("CCODEGRAPH_CLINK", "clink"))


def load_graph_indexes(con: sqlite3.Connection) -> tuple[dict[str, list[Def]],
                                                          dict[str, list[Def]]]:
    """從既有 graph.db 重建 fn/gv 歸戶索引(D1 規則沿用)。"""
    fn_index: dict[str, list[Def]] = {}
    gv_index: dict[str, list[Def]] = {}
    for nid, name, kind, file, ls, le, st in con.execute(
            "SELECT id,name,kind,file,line_start,line_end,is_static "
            "FROM nodes WHERE kind IN ('function','global')"):
        d: Def = {"id": nid, "name": name, "kind": kind, "file": file,
                  "line_start": ls, "line_end": le, "is_static": bool(st)}
        (fn_index if kind == "function" else gv_index) \
            .setdefault(name, []).append(d)
    return fn_index, gv_index


def clink_import(root: str, db_path: str,
                 compdb: str | None = None) -> None:
    """R7a:跑 clink -b 產 SQLite,翻譯成我們的邊(origin=clink)。
    category 語意(實測驗證,research/clink.md):1=call(parent=解析期歸戶)、
    4=assignment。層可重跑:先刪舊 clink 邊。D7:整合不重寫。"""
    if not os.path.exists(db_path):
        sys.exit(f"ERROR: no graph at {db_path} — run build first")
    try:
        subprocess.run([CLINK_BIN, "--version"], capture_output=True)
    except FileNotFoundError:
        sys.exit("ERROR: clink not found — R7a 是選配層。"
                 "安裝:git clone https://github.com/Smattr/clink && cmake …;"
                 "或設 CCODEGRAPH_CLINK=/path/to/clink")
    t0 = time.time()
    base = os.path.splitext(os.path.basename(db_path))[0]
    cdb = os.path.join(root, PRODUCTS_DIR, f"{base}.clink.db")
    # L4/D12 compile DB 階梯:--compdb 合併 → root/build 偵測 → 合成(ccq 血統)
    pdir = os.path.join(root, PRODUCTS_DIR)
    cc_dir = None
    if compdb:
        paths = [os.path.abspath(os.path.join(root, p)) if not os.path.isabs(p)
                 else p for p in compdb.split(",")]
        entries, conflicts = merge_compile_dbs(paths)
        with open(os.path.join(pdir, "compile_commands.json"), "w") as fh:
            json.dump(entries, fh)
        cc_dir = pdir
        conf = 0.95
        mode = (f"merged({len(paths)} DBs -> {len(entries)} files, "
                f"{len(conflicts)} conflicts)")
        if conflicts:
            print(f"[D12] 同檔跨 DB 規則衝突 {len(conflicts)} 筆"
                  f"(前者優先;順序=你給的參數順序):")
            for c in conflicts[:5]:
                print(f"      {c}")
            if len(conflicts) > 5:
                print(f"      … +{len(conflicts) - 5} more")
    else:
        for cand in (root, os.path.join(root, "build")):
            if os.path.exists(os.path.join(cand, "compile_commands.json")):
                cc_dir = cand
                break
        if cc_dir:
            conf = 0.95
            mode = f"compile-DB({cc_dir})"
        else:
            entries = synthesize_compile_db(root, source_files(root))
            with open(os.path.join(pdir, "compile_commands.json"), "w") as fh:
                json.dump(entries, fh)
            cc_dir = pdir
            conf = CONFIDENCE["clink"]
            mode = f"synthesized({len(entries)} entries;無真實 -D,單 config 盲點仍在)"
    # 增量語意(#6):clink 自帶每檔 hash 增量——保留 clink.db,重跑
    # clink-import 時它只重解析變更檔;compile-DB 模式變更才全重解析。
    mode_file = os.path.join(pdir, f"{base}.clink_mode.txt")
    prev_mode = None
    if os.path.exists(mode_file):
        with open(mode_file) as fh:
            prev_mode = fh.read().strip()
    if prev_mode is not None and prev_mode != mode and os.path.exists(cdb):
        print(f"[R7a/L4] compile-DB 模式變更({prev_mode} → {mode})— "
              f"清 clink.db 全重解析")
        os.remove(cdb)
    with open(mode_file, "w") as fh:
        fh.write(mode)
    print(f"[R7a/L4] clink -b(libclang,{mode},conf {conf};"
          f"{'增量' if os.path.exists(cdb) else '全量'})…")
    cmd = [CLINK_BIN, "-b", "--database", cdb]
    if cc_dir:
        cmd += ["--compile-commands", cc_dir]
    run_checked([*cmd, "."], root)

    con = sqlite3.connect(db_path)
    fn_index, gv_index = load_graph_indexes(con)
    con.execute("DELETE FROM edges WHERE origin='clink'")

    src_con = sqlite3.connect(f"file:{cdb}?mode=ro", uri=True)
    ver = src_con.execute("PRAGMA user_version").fetchone()[0]
    if ver != 1:
        sys.exit(f"ERROR: clink db schema user_version={ver},匯入器只認 1 — "
                 f"clink 改版了,請更新 clink_import 的欄位對映(P7:不靜默讀壞)")
    n_calls = n_writes = n_drop = 0
    for cat, name, parent, path, line in src_con.execute(
            "SELECT s.category, s.name, s.parent, r.path, s.line "
            "FROM symbols s JOIN records r ON r.id = s.path "
            "WHERE s.category IN (1, 4)"):
        if not parent:
            continue
        if os.path.isabs(path):
            path = os.path.relpath(os.path.realpath(path),
                                   os.path.realpath(root))
        src = attribute_src(fn_index, parent, path, line)
        if not src:
            n_drop += 1
            continue
        index = fn_index if cat == 1 else gv_index
        kind = "calls" if cat == 1 else "writes"
        viable = choose_dst(index.get(name, []), path)
        meta = edge_meta(len(viable))
        for dst in viable:
            if dst["id"] != src["id"]:
                con.execute(
                    "INSERT OR IGNORE INTO edges (src,dst,kind,file,line,"
                    "origin,confidence,meta) VALUES (?,?,?,?,?,'clink',?,?)",
                    (src["id"], dst["id"], kind, path, line, conf, meta))
                if kind == "calls":
                    n_calls += 1
                else:
                    n_writes += 1
    # L4/D3 註記:語意引擎的 confirmed/absent 寫進 meta,不動 confidence
    #(D3 重估結論:維持 meta-only——「clangd 說沒有」在 #ifdef 情境是線索
    # 不是裁決,判讀交給 LLM;使用者 2026-07-05 裁決不變)
    n_conf, n_abs = 0, 0
    con.execute("""CREATE TEMP TABLE clink_pairs AS
        SELECT DISTINCT src, dst, kind FROM edges WHERE origin='clink'""")
    cur = con.execute("""UPDATE edges SET meta = json_set(meta,
          '$.semantic', CASE WHEN EXISTS (SELECT 1 FROM clink_pairs cp
              WHERE cp.src=edges.src AND cp.dst=edges.dst AND cp.kind=edges.kind)
            THEN 'confirmed' ELSE 'absent' END,
          '$.semantic_by', 'clink')
        WHERE origin='cscope' AND kind IN ('calls','writes')""")
    n_ann = cur.rowcount
    n_conf = con.execute("SELECT COUNT(*) FROM edges WHERE origin='cscope' "
                         "AND instr(meta,'\"semantic\":\"confirmed\"')"
                         ">0").fetchone()[0]
    n_abs = n_ann - n_conf
    engines = json.loads(con.execute(
        "SELECT value FROM meta WHERE key='engines_run'").fetchone()[0])
    engines.append({"engine": "clink", "layer": "R7a+L4", "mode": mode,
                    "seconds": round(time.time() - t0, 1)})
    hrow = con.execute("SELECT value FROM meta WHERE key='history'").fetchone()
    hist = json.loads(hrow[0]) if hrow else []
    hist.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "action": "clink-import", "mode": mode,
                 "calls": n_calls, "writes": n_writes, "dropped": n_drop,
                 "confirmed": n_conf, "absent": n_abs,
                 "seconds": round(time.time() - t0, 1)})
    if hrow:
        con.execute("UPDATE meta SET value=? WHERE key='history'",
                    (json.dumps(hist, ensure_ascii=False),))
    else:
        con.execute("INSERT INTO meta VALUES ('history',?)",
                    (json.dumps(hist, ensure_ascii=False),))
    con.execute("UPDATE meta SET value=? WHERE key='engines_run'",
                (json.dumps(engines),))
    con.commit()
    print(f"done: +calls={n_calls}, +writes={n_writes} (origin=clink, "
          f"conf {conf}); dropped(no-src)={n_drop}; "
          f"semantic 註記: confirmed={n_conf}, absent={n_abs}; "
          f"{time.time() - t0:.0f}s")


# ---------------------------------------------------------------- #1: viz

CALL_FAMILY = ("calls", "fnptr", "callback")
ALL_VIZ_KINDS = ("calls", "fnptr", "callback", "expands", "reads", "writes",
                 "includes", "co_changes")
VIZ_LINK_COLORS = {"calls": "#607d8b", "fnptr": "#ffb300",
                   "callback": "#ab47bc", "expands": "#26a69a",
                   "reads": "#66bb6a", "writes": "#ef5350",
                   "includes": "#8d6e63", "co_changes": "#78909c"}
VIZ_NODE_COLORS = {"function": "#4fc3f7", "global": "#66bb6a",
                   "macro": "#ffa726", "file": "#8d6e63"}
MODULE_PALETTE = ["#4fc3f7", "#ffb300", "#ab47bc", "#66bb6a", "#ef5350",
                  "#26a69a", "#8d6e63", "#f06292", "#9ccc65", "#7986cb"]


def viz_focus_filter(nodes: list[dict[str, Any]], links: list[dict[str, Any]],
                     focus: str, depth: int) -> tuple[list[dict[str, Any]],
                                                      list[dict[str, Any]]]:
    """無向 BFS 鄰域(ccq focusFilter 血統);focus 可為 name 或 qname。"""
    adj: dict[str, list[str]] = {}
    for e in links:
        adj.setdefault(e["source"], []).append(e["target"])
        adj.setdefault(e["target"], []).append(e["source"])
    seeds = [n["id"] for n in nodes
             if n["id"] == focus or n["id"].endswith("::" + focus)
             or n["id"].rsplit("::", 1)[-1] == focus]
    keep = set(seeds)
    frontier = list(seeds)
    for _ in range(max(1, depth)):
        nxt: list[str] = []
        for nid in frontier:
            for m in adj.get(nid, []):
                if m not in keep:
                    keep.add(m)
                    nxt.append(m)
        frontier = nxt
    for n in nodes:
        n["focus"] = n["id"] in seeds
    return ([n for n in nodes if n["id"] in keep],
            [e for e in links if e["source"] in keep and e["target"] in keep])


def viz_cmd(root: str, db: str, fmt: str, focus: str | None, depth: int,
            out: str | None, full: bool, min_conf: float) -> None:
    """#1:從 graph.db 匯出單一離線互動 HTML(2d/3d;ccq viz parity)。
    預設只嵌呼叫家族(calls/fnptr/callback);--full 嵌全部 8 種邊。
    不索引——沒 artifact 就報錯給正確第一步(P7)。"""
    if fmt not in ("html3d", "html2d", "3d", "2d"):
        sys.exit(f"unknown --format {fmt!r} (html3d|html2d)")
    dim = "3d" if fmt in ("html3d", "3d") else "2d"
    if not os.path.exists(db):
        sys.exit(f"ERROR: no graph at {db} — run: ccodegraph.py build -p {root}")
    # 過舊警告(mtime 快篩;精確判定用 build --incremental)
    db_m = os.path.getmtime(db)
    newest = 0.0
    for p in source_files(root):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(root, p)))
        except OSError:
            continue
    if newest > db_m:
        print("warning: graph is older than the source tree — run "
              "`build --incremental` first", file=sys.stderr)
    kinds = ALL_VIZ_KINDS if full else CALL_FAMILY
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ph = ",".join("?" * len(kinds))
    links = [{"source": sq, "target": dq, "kind": k}
             for sq, dq, k in con.execute(
                 f"SELECT DISTINCT n1.qname, n2.qname, e.kind FROM edges e "
                 f"JOIN nodes n1 ON n1.id=e.src JOIN nodes n2 ON n2.id=e.dst "
                 f"WHERE e.kind IN ({ph}) AND e.confidence >= ?",
                 (*kinds, min_conf))]
    used = {x for e in links for x in (e["source"], e["target"])}
    have_module = any(r[1] == "module"
                      for r in con.execute("PRAGMA table_info(nodes)"))
    if not have_module:
        print("note: graph is schema v1(無 module 欄)— 重跑 build 可升級",
              file=sys.stderr)
    msel = "COALESCE(module,'')" if have_module else "''"
    mods: dict[str, str] = {}
    nodes = []
    for qn, kind, nfile, line, module in con.execute(
            f"SELECT qname, kind, file, line_start, {msel} FROM nodes"):
        if qn not in used:
            continue
        color = VIZ_NODE_COLORS.get(kind, "#b0bec5")
        if module:
            if module not in mods:
                mods[module] = MODULE_PALETTE[len(mods) % len(MODULE_PALETTE)]
            color = mods[module]        # module 分群(視覺):同 module 同色
        nodes.append({"id": qn, "kind": kind, "file": nfile, "line": line,
                      "module": module, "color": color, "focus": False})
    con.close()
    if focus:
        nodes, links = viz_focus_filter(nodes, links, focus, depth)
        if not nodes:
            sys.exit(f'ERROR: focus symbol "{focus}" not in the embedded '
                     f'edge kinds({",".join(kinds)})')
    adir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    lib = os.path.join(adir, "fg2d.js" if dim == "2d" else "tfg3d.js")
    tpl = os.path.join(adir, "viz_template.html")
    try:
        with open(lib) as fh:
            libjs = fh.read()
        with open(tpl) as fh:
            template = fh.read()
    except OSError as e:
        sys.exit(f"ERROR: viz asset missing: {e}")
    cbs = []
    for k in kinds:
        chk = " checked" if k in CALL_FAMILY else ""
        cbs.append(f'<label><input type="checkbox" class="fk" '
                   f'data-kind="{k}"{chk}> <span class="sw" '
                   f'style="background:{VIZ_LINK_COLORS[k]}"></span>{k}</label>')
    data = json.dumps({"nodes": nodes, "links": links,
                       "focus": focus or ""}, ensure_ascii=False)
    h = template
    h = h.replace("__DIM__", dim.upper())
    h = h.replace("__CTOR__", "ForceGraph" if dim == "2d" else "ForceGraph3D")
    h = h.replace("__KINDCB__", "\n ".join(cbs))
    h = h.replace("__LINKCOLORS__", json.dumps(VIZ_LINK_COLORS))
    h = h.replace("__LIB__", libjs)
    h = h.replace("__DATA__", data)
    dest = out or os.path.join(root, PRODUCTS_DIR, f"graph-{dim}.html")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as fh:
        fh.write(h)
    print(f"wrote {dest}: {len(nodes)} nodes, {len(links)} edges "
          f"(kinds: {','.join(kinds)}{'' if full else '; add --full for all'})")




# ---------------------------------------------------------------- 查詢動詞
# R4:每個動詞先產出資料結構(dict),再依 --json / 文字渲染(FR9 雙軌,
# 欄位一一對應)。文字格式即 golden——測試釘住。

QUERY_KINDS = ("calls", "fnptr", "callback", "expands")


def fmt_site(padded: str | None) -> str:
    """edge_pairs.first_site 是 printf('%s:%09d') 的可排序形式 → 還原顯示。"""
    if not padded:
        return "?"
    f, _, n = padded.rpartition(":")
    return f"{f}:{int(n)}" if n.isdigit() else padded


def parse_meta(meta_json: str | None) -> dict[str, Any]:
    try:
        m: dict[str, Any] = json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        m = {}
    return m


def fmt_tags(origins: str, meta: dict[str, Any]) -> str:
    tags = [origins]
    if meta.get("ambiguous"):
        tags.append(f'ambiguous {meta.get("candidates", "?")} candidates')
    if "semantic" in meta:
        tags.append(f'semantic:{meta["semantic"]}')
    return "[" + "; ".join(tags) + "]"


def node_candidates(con: sqlite3.Connection, sym: str,
                    kinds: list[str]) -> list[tuple[Any, ...]]:
    ph = ",".join("?" * len(kinds))
    return con.execute(
        f"SELECT id,name,qname,kind,file,line_start,is_static,signature "
        f"FROM nodes WHERE (name=? OR qname=?) AND kind IN ({ph}) "
        f"ORDER BY file", (sym, sym, *kinds)).fetchall()


def pair_items(con: sqlite3.Connection, nid: int, direction: str,
               kinds: tuple[str, ...], min_conf: float) -> list[dict[str, Any]]:
    """pair 級去重列(D2):對向 qname + 首站點 + 站點數 + origins + meta。"""
    other = "src" if direction == "dst" else "dst"
    ph = ",".join("?" * len(kinds))
    rows = con.execute(
        f"SELECT n.qname, p.first_site, p.site_count, p.origins, "
        f"p.confidence, "
        f"(SELECT meta FROM edges e WHERE e.{direction}=p.{direction} "
        f" AND e.{other}=p.{other} AND e.kind=p.kind "
        f" ORDER BY (e.meta = '{{}}'), e.origin LIMIT 1) "
        f"FROM edge_pairs p JOIN nodes n ON n.id=p.{other} "
        f"WHERE p.{direction}=? AND p.kind IN ({ph}) "
        f"AND p.confidence >= ? ORDER BY n.qname",
        (nid, *kinds, min_conf)).fetchall()
    return [{"qname": qn, "site": fmt_site(site), "sites": nsites,
             "origins": origins.split(","), "confidence": conf,
             "tags": parse_meta(meta)}
            for qn, site, nsites, origins, conf, meta in rows]


def fmt_item(it: dict[str, Any]) -> str:
    extra = f" ({it['sites']} sites)" if it["sites"] > 1 else ""
    return (f"- {it['qname']}  @ {it['site']}{extra}  "
            f"{fmt_tags(','.join(it['origins']), it['tags'])}")


def truncate_items(items: list[Any],
                   limit: int) -> tuple[list[Any], int, bool]:
    """D16:顯式截斷。回傳 (截後列表, 真實總數, 是否截斷);limit<=0 = 不限。"""
    total = len(items)
    if limit > 0 and total > limit:
        return items[:limit], total, True
    return items, total, False


def fmt_truncation(shown: int, total: int) -> str:
    """D16:截斷尾行。真實總數必須可見,agent 才能決定要不要 --limit 0 重查。"""
    return f"… +{total - shown} more (total {total}; use --limit 0 for all)"


def q_sectioned(con: sqlite3.Connection, sym: str, direction: str,
                min_conf: float,
                limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    cands = node_candidates(con, sym, ["function", "macro"])
    verb = "callers" if direction == "dst" else "callees"
    res: dict[str, Any] = {"verb": verb, "symbol": sym,
                           "min_conf": min_conf, "definitions": []}
    for cid, _n, qname, kind, file, line, _st, sig in cands:
        items, total, trunc = truncate_items(
            pair_items(con, cid, direction, QUERY_KINDS, min_conf), limit)
        res["definitions"].append({
            "qname": qname, "kind": kind, "file": file, "line": line,
            "signature": sig,
            "items": items, "total": total, "truncated": trunc})
    return res


def render_sectioned(res: dict[str, Any]) -> None:
    defs = res["definitions"]
    if not defs:
        print(f'symbol "{res["symbol"]}" not found (kind=function|macro)')
        return
    if len(defs) > 1:
        print(f"{res['verb']} of {res['symbol']} — {len(defs)} definitions"
              f"(分節;可用 qname 精確指定):\n")
    for d in defs:
        if len(defs) > 1:
            print(f"## {d['qname']} 的定義 @ {d['file']}:{d['line']}")
        if not d["items"]:
            print("- (none)")
        for it in d["items"]:
            print(fmt_item(it))
        if d.get("truncated"):
            print(fmt_truncation(len(d["items"]), d["total"]))
        if len(defs) > 1:
            print()


def q_explore(con: sqlite3.Connection, sym: str, min_conf: float,
              limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    """R4 頭牌動詞:一發 = 定義 + callers + callees + 全域讀寫 + 巨集使用。"""
    cands = node_candidates(con, sym, ["function"])
    res: dict[str, Any] = {"verb": "explore", "symbol": sym,
                           "min_conf": min_conf, "definitions": []}
    for cid, _n, qname, _k, file, line, _st, sig in cands:
        callees_all = pair_items(con, cid, "src", QUERY_KINDS, min_conf)
        gl = con.execute(
            "SELECT n2.qname, e.kind, e.file, e.line FROM edges e "
            "JOIN nodes n2 ON n2.id=e.dst WHERE e.src=? AND e.kind IN "
            "('reads','writes') AND e.confidence >= ? "
            "ORDER BY n2.qname, e.kind", (cid, min_conf)).fetchall()
        callers, callers_total, callers_tr = truncate_items(
            pair_items(con, cid, "dst", QUERY_KINDS, min_conf), limit)
        callees, callees_total, callees_tr = truncate_items(callees_all, limit)
        globs, globs_total, globs_tr = truncate_items(
            [{"qname": g, "access": k, "site": f"{gf}:{gl_}"}
             for g, k, gf, gl_ in gl], limit)
        res["definitions"].append({
            "qname": qname, "file": file, "line": line, "signature": sig,
            "callers": callers, "callers_total": callers_total,
            "callers_truncated": callers_tr,
            "callees": callees, "callees_total": callees_total,
            "callees_truncated": callees_tr,
            "globals": globs, "globals_total": globs_total,
            "globals_truncated": globs_tr,
        })
    return res


def render_explore(res: dict[str, Any]) -> None:
    defs = res["definitions"]
    if not defs:
        print(f'symbol "{res["symbol"]}" not found (kind=function)')
        return
    for d in defs:
        sig = f"  {d['signature']}" if d["signature"] else ""
        print(f"== {d['qname']} @ {d['file']}:{d['line']}{sig}")
        print(f"callers ({d['callers_total']}):")
        for it in d["callers"]:
            print("  " + fmt_item(it))
        if d["callers_truncated"]:
            print("  " + fmt_truncation(len(d["callers"]), d["callers_total"]))
        print(f"callees ({d['callees_total']}):")
        for it in d["callees"]:
            print("  " + fmt_item(it))
        if d["callees_truncated"]:
            print("  " + fmt_truncation(len(d["callees"]), d["callees_total"]))
        print(f"globals ({d['globals_total']}):")
        for g in d["globals"]:
            print(f"  - {g['qname']}  [{g['access']}]  @ {g['site']}")
        if d["globals_truncated"]:
            print("  " + fmt_truncation(len(d["globals"]), d["globals_total"]))
        print()


def run_sql(con: sqlite3.Connection, query: str, cap: int) -> None:
    """D16:sql 逃生口的顯式行數上限(cap<=0 = 不限)。不改寫使用者 SQL、
    不隱性截斷——超限時停止並明講「還有更多」,由 agent 決定加 LIMIT/OFFSET、
    改彙總、或 --limit 0 全量重跑。"""
    for shown, row in enumerate(con.execute(query)):
        if cap > 0 and shown >= cap:
            print(f"… truncated at {cap} rows (more remain) — "
                  f"add LIMIT/OFFSET, aggregate, or rerun with --limit 0")
            break
        print("|".join(str(c) for c in row))


def q_schema(con: sqlite3.Connection) -> dict[str, Any]:
    res: dict[str, Any] = {"verb": "schema", "nodes": {}, "edges": [],
                           "pending": [], "warnings": []}
    for kind, cnt in con.execute(
            "SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY kind"):
        res["nodes"][kind] = cnt
    for kind, origin, cnt in con.execute(
            "SELECT kind, origin, COUNT(*) FROM edges "
            "GROUP BY kind, origin ORDER BY kind"):
        res["edges"].append({"kind": kind, "origin": origin, "count": cnt})
    row = con.execute("SELECT value FROM meta WHERE key='engines_run'").fetchone()
    res["engines_run"] = json.loads(row[0]) if row else []
    root_row = con.execute("SELECT value FROM meta WHERE key='root'").fetchone()
    stored = con.execute(
        "SELECT value FROM meta WHERE key='manual_src_hash'").fetchone()
    if root_row:
        fp = os.path.join(root_row[0], "fnptr.json")
        cur = None
        if os.path.exists(fp):
            with open(fp, "rb") as fh:
                cur = hashlib.sha256(fh.read()).hexdigest()
        if stored and cur != stored[0]:
            res["warnings"].append(
                "fnptr.json changed since build — manual edges are STALE; "
                "re-run build")
        elif stored and cur is None:
            res["warnings"].append(
                "fnptr.json deleted since build — manual edges are STALE; "
                "re-run build")
        elif cur and not stored:
            res["warnings"].append(
                "fnptr.json present but not in this graph — re-run build "
                "to ingest it")
    filled = {r[0] for r in con.execute("SELECT DISTINCT origin FROM edges")}
    for origin, desc in PENDING_LAYERS:
        if origin not in filled:
            res["pending"].append({"origin": origin, "desc": desc})
    return res


def render_schema(res: dict[str, Any]) -> None:
    for w in res["warnings"]:
        print(f"WARNING: {w}" if "STALE" in w else f"note: {w}")
    print("nodes:")
    for kind, cnt in res["nodes"].items():
        print(f"  {kind:10s} {cnt}")
    print("edges (kind x origin):")
    for e in res["edges"]:
        print(f"  {e['kind']:10s} [{e['origin']}] {e['count']}")
    print("pending(空格子,design §5):")
    for p in res["pending"]:
        print(f"  {p['origin']:12s} {p['desc']}")


SKILL_INSTALL_DIRS = [
    "~/.claude/skills/ccodegraph", "~/.agents/skills/ccodegraph",
    "./.claude/skills/ccodegraph", "./.agents/skills/ccodegraph",
]


KNOWN_ENV = ["CCODEGRAPH_CTAGS_PATH", "CCODEGRAPH_CSCOPE_PATH",
             "CCODEGRAPH_CLINK_PATH", "CCODEGRAPH_CLINK",
             "CCODEGRAPH_GIT_PATH"]


def q_status(root: str, db: str, full: bool = False) -> dict[str, Any]:
    """維護動詞(ccq status 血統):偵錯分診的第一手資料。--full 給支援工程師。
    JSON 版含 status_schema_version 與穩定 issues[] 代碼,供自動分診腳本用
    (codex 支援工程師審查後補強)。"""
    import platform as _platform
    issues: list[dict[str, str]] = []

    def issue(sev: str, code: str, detail: str, action: str) -> None:
        issues.append({"severity": sev, "code": code,
                       "detail": detail, "action": action})

    res: dict[str, Any] = {"verb": "status", "status_schema_version": 1,
                           "root": root, "ccodegraph": VERSION,
                           "ccodegraph_path": os.path.abspath(__file__),
                           "cwd": os.getcwd(),
                           "python": sys.version.split()[0],
                           "platform": _platform.platform()}
    res["env"] = {k: os.environ.get(k) for k in KNOWN_ENV
                  if full or k in os.environ}
    unknown = sorted(k for k in os.environ
                     if k.startswith("CCODEGRAPH_") and k not in KNOWN_ENV)
    res["env_unknown"] = unknown
    if unknown:
        issue("warn", "ENV_UNKNOWN_VARS",
              f"未知的 CCODEGRAPH_* 變數(拼錯?):{', '.join(unknown)}",
              f"合法名:{', '.join(KNOWN_ENV)}")
    tools = {}
    for t in ("ctags", "cscope", "clink", "git"):
        p = tool_path(t) if t != "clink" else CLINK_BIN
        ok = True
        flavor = None
        try:
            r = subprocess.run([p, "--version"], capture_output=True, text=True)
            ver = (r.stdout or r.stderr).splitlines()[0].strip() if \
                (r.stdout or r.stderr) else "?"
            if t == "ctags":
                flavor = classify_ctags(r.stdout + r.stderr)
                ok = flavor == "universal"
        except FileNotFoundError:
            ver = "not found"
            ok = False
        env = f"CCODEGRAPH_{t.upper()}_PATH"
        tools[t] = {"path": p, "version": ver, "ok": ok, "flavor": flavor,
                    "env_override": env in os.environ
                    or (t == "clink" and "CCODEGRAPH_CLINK" in os.environ)}
        if not ok and t in ("ctags", "cscope"):
            code = ("CTAGS_NOT_UNIVERSAL" if t == "ctags" and flavor
                    else f"TOOL_MISSING_{t.upper()}")
            issue("error", code, f"{t}: {ver}(path={p})",
                  "見 build 錯誤訊息內的各平台安裝指引")
        if t == "clink" and not ok:
            issue("info", "CLINK_MISSING",
                  "clink 未安裝——語意層(選配)不可用",
                  "可忽略;要裝見 README 進階章")
    res["tools"] = tools
    found = [os.path.expanduser(d) for d in SKILL_INSTALL_DIRS
             if os.path.exists(os.path.join(os.path.expanduser(d), "SKILL.md"))]
    embedded_hash = hashlib.sha256(SKILL_MD.encode()).hexdigest()
    stale_at = []
    for d in found:
        with open(os.path.join(d, "SKILL.md"), "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != embedded_hash:
                stale_at.append(d)
    res["skill"] = {"installed": found, "stale": stale_at,
                    "hint": None if found else
                    "ccodegraph.py skill > ~/.claude/skills/ccodegraph/SKILL.md"}
    if not found:
        issue("info", "SKILL_MISSING", "agent skill 未安裝",
              "ccodegraph.py skill > ~/.claude/skills/ccodegraph/SKILL.md")
    elif stale_at:
        issue("warn", "SKILL_STALE",
              f"已安裝的 SKILL 與本版內容不同:{'; '.join(stale_at)}",
              "重跑 skill 動詞覆蓋安裝")
    pdir = os.path.join(root, PRODUCTS_DIR)
    prods = []
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            fp = os.path.join(pdir, fn)
            st = os.stat(fp)
            prods.append({"path": fp, "size": st.st_size,
                          "mtime": time.strftime("%Y-%m-%d %H:%M",
                                                 time.localtime(st.st_mtime))})
    res["products"] = prods
    res["databases"] = [str(p["path"]) for p in prods
                        if str(p["path"]).endswith(".db")
                        and not str(p["path"]).endswith(".clink.db")]
    if not os.path.exists(db):
        res["artifact"] = None
        issue("error", "NO_GRAPH", f"沒有圖:{db}",
              f"ccodegraph.py build -p {root}")
        res["issues"] = issues
        res["health"] = "ERROR"
        res["suggestion"] = f"no graph — run: ccodegraph.py build -p {root}"
        return res
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    hist = json.loads(meta.get("history", "[]"))
    art: dict[str, Any] = {
        "db_label": meta.get("db_label"),
        "schema_version": meta.get("schema_version"),
        "engines_run": json.loads(meta.get("engines_run", "[]")),
        "history_tail": hist[-5:] if full else hist[-1:],
        "nodes": con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": con.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
    }
    row = con.execute("SELECT git_rev FROM files WHERE git_rev IS NOT NULL "
                      "LIMIT 1").fetchone()
    art["built_at_git"] = row[0][:12] if row and row[0] else None
    art["root_recorded"] = meta.get("root")
    art["root_match"] = (os.path.realpath(meta.get("root", root))
                         == os.path.realpath(root))
    if not art["root_match"]:
        issue("error", "ROOT_MISMATCH",
              f"這張圖是為別的 root 建的:{meta.get('root')}",
              "確認 -p / --db 是否配對錯誤,或重建")
    if meta.get("schema_version") != "2":
        issue("warn", "SCHEMA_OLD",
              f"schema v{meta.get('schema_version')}(現行 v2)",
              "重跑 build 升級")
    res["artifact"] = art
    head = git_head(root)
    res["git_now"] = head[:12] if head else None
    if art["built_at_git"] and res["git_now"] \
            and art["built_at_git"] != res["git_now"]:
        issue("info", "GIT_MOVED",
              f"建圖時 git={art['built_at_git']},現在 {res['git_now']}",
              "drift 清單才是精確判準(hash 級)")
    # clink 摘要(codex:匯入健康)
    base = os.path.splitext(os.path.basename(db))[0]
    cdbp = os.path.join(pdir, f"{base}.clink.db")
    clink_info: dict[str, Any] = {"sidecar": cdbp,
                                  "exists": os.path.exists(cdbp)}
    last_imp = next((h for h in reversed(hist)
                     if h.get("action") == "clink-import"), None)
    clink_info["last_import"] = last_imp
    res["clink"] = clink_info
    if last_imp and "synthesized" in str(last_imp.get("mode", "")):
        issue("info", "CLINK_SYNTHESIZED",
              "語意層用合成 compile DB(無真實 -D,單 config 盲點)",
              "有真 compile_commands.json 時放 root/build/ 或 --compdb")
    # compile DB 覆蓋率
    ccj = os.path.join(pdir, "compile_commands.json")
    for cand in (os.path.join(root, "compile_commands.json"),
                 os.path.join(root, "build", "compile_commands.json"), ccj):
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as fh2:
                    entries = len(json.load(fh2))
            except (OSError, json.JSONDecodeError):
                entries = -1
            res["compile_db"] = {"path": cand, "entries": entries}
            break
    else:
        res["compile_db"] = None
    old_hashes = dict(con.execute(
        "SELECT path, content_hash FROM files WHERE content_hash IS NOT NULL"))
    con.close()
    srcs = source_files(root)
    new_hashes = {p: file_hash(os.path.join(root, p)) for p in srcs}
    changed, added, deleted = compute_changes(old_hashes, new_hashes)
    drift = sorted(changed | added | deleted)
    res["drift"] = {"changed": len(changed), "added": len(added),
                    "deleted": len(deleted), "total": len(drift),
                    "files": drift if full else drift[:5],
                    "truncated": (not full) and len(drift) > 5}
    if drift:
        issue("warn", "STALE_GRAPH",
              f"{len(drift)} 檔與圖不一致",
              f"ccodegraph.py build --incremental -p {root}")
    res["suggestion"] = (
        f"{len(drift)} file(s) differ from the graph — run: "
        f"ccodegraph.py build --incremental -p {root}" if drift
        else "graph is aligned with the source tree")
    res["issues"] = issues
    sevs = {i["severity"] for i in issues}
    res["health"] = ("ERROR" if "error" in sevs
                     else "WARN" if "warn" in sevs else "OK")
    return res


def render_status(res: dict[str, Any], full: bool = False) -> None:
    print(f"ccodegraph {res['ccodegraph']} status — {res['root']}")
    print(f"health : {res.get('health', '?')}")
    for i in res.get("issues", []):
        print(f"  [{i['severity'].upper()}] {i['code']}: {i['detail']}")
        print(f"           → {i['action']}")
    print(f"env    : python {res['python']} · {res['platform']}")
    if full:
        print(f"  ccodegraph_path = {res['ccodegraph_path']}")
        print(f"  cwd = {res['cwd']}")
    if res["env"]:
        for k, v in res["env"].items():
            print(f"  {k} = {v if v is not None else '(unset)'}")
    if res.get("env_unknown"):
        print(f"  !! 未知 CCODEGRAPH_* 變數:{', '.join(res['env_unknown'])}")
    print("tools:")
    for t, info in res["tools"].items():
        ov = "  (env override)" if info["env_override"] else ""
        mark = "✓" if info.get("ok") else "✗"
        print(f"  {mark} {t:7s} {info['path']}  —  {info['version']}{ov}")
    sk = res["skill"]
    if sk["installed"]:
        stale = f"(STALE: {'; '.join(sk['stale'])})" if sk.get("stale") else ""
        print("skill  : " + "; ".join(sk["installed"]) + stale)
    else:
        print(f"skill  : not installed — {sk['hint']}")
    if res.get("databases"):
        hint = ("   (dumpdb --db <f> 看 metadata;自訂路徑外的 DB "
                "status/reset 管不到)" if full else "")
        print("databases: " + "; ".join(
            os.path.basename(d) for d in res["databases"]) + hint)
    if full:
        print("products:")
        for p in res["products"]:
            print(f"  {p['path']}  {p['size']:,} B  {p['mtime']}")
        if not res["products"]:
            print("  (none)")
    else:
        tot = sum(p["size"] for p in res["products"])
        print(f"products: {len(res['products'])} files, {tot:,} B "
              f"(--full 逐項列出)")
    art = res.get("artifact")
    if art:
        print(f"artifact: {art.get('db_label') or 'graph.db'} schema "
              f"v{art['schema_version']}, "
              f"{art['nodes']} nodes, {art['edges']} edges")
        for e in art["engines_run"]:
            layers = e.get("layers") or e.get("layer") or ""
            print(f"  engine : {e.get('engine')} {layers} "
                  f"mode={e.get('mode', '')} {e.get('seconds', '')}s")
        for h in art.get("history_tail", []):
            print(f"  history: {h.get('ts')} {h.get('action')}"
                  + (f" mode={h['mode']}" if h.get('mode') else ""))
        if art.get("built_at_git"):
            m = "==" if art["built_at_git"] == res.get("git_now") else "≠"
            print(f"  git    : built@{art['built_at_git']} {m} "
                  f"now@{res.get('git_now')}")
    ck = res.get("clink")
    if ck:
        li = ck.get("last_import")
        if li:
            print(f"clink  : sidecar={'✓' if ck['exists'] else '✗'} "
                  f"last-import calls={li.get('calls')} "
                  f"writes={li.get('writes')} dropped={li.get('dropped')} "
                  f"confirmed={li.get('confirmed')} absent={li.get('absent')}")
        else:
            print("clink  : 尚未匯入(選配;clink-import)")
    cdb = res.get("compile_db")
    if cdb:
        print(f"compile_db: {cdb['path']}({cdb['entries']} entries)")
    d = res.get("drift")
    if d and d["files"]:
        print(f"drift  : total={d['total']} (changed={d['changed']} "
              f"added={d['added']} deleted={d['deleted']}): "
              f"{', '.join(d['files'])}"
              + (" …(--full 全列)" if d.get("truncated") else ""))
    print(f"→ {res['suggestion']}")


def q_dumpdb(db: str) -> dict[str, Any]:
    """Q1d:印 DB 完整 metadata——label、schema、寫入歷史(append-only)、
    各層統計。這是核心資料的身份證(使用者要求)。"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    res: dict[str, Any] = {
        "verb": "dumpdb", "path": os.path.abspath(db),
        "db_label": meta.get("db_label", os.path.basename(db)),
        "schema_version": meta.get("schema_version"),
        "root": meta.get("root"),
        "history": json.loads(meta.get("history", "[]")),
        "engines_run": json.loads(meta.get("engines_run", "[]")),
        "manual_src_hash": meta.get("manual_src_hash"),
        "nodes": dict(con.execute(
            "SELECT kind, COUNT(*) FROM nodes GROUP BY kind")),
        "edges": [{"kind": k, "origin": o, "count": c} for k, o, c in
                  con.execute("SELECT kind, origin, COUNT(*) FROM edges "
                              "GROUP BY kind, origin")],
    }
    con.close()
    return res


def render_dumpdb(res: dict[str, Any]) -> None:
    print(f"db      : {res['db_label']}  ({res['path']})")
    print(f"schema  : v{res['schema_version']}   root: {res['root']}")
    print("history (append-only):")
    for h in res["history"]:
        extra = "".join(f" {k}={v}" for k, v in h.items()
                        if k not in ("ts", "action") and v is not None)
        print(f"  {h['ts']}  {h['action']}{extra}")
    if not res["history"]:
        print("  (pre-history db — rebuild to start the log)")
    print("nodes   : " + ", ".join(f"{k}={v}" for k, v in res["nodes"].items()))
    print("edges   :")
    for e in res["edges"]:
        print(f"  {e['kind']:10s} [{e['origin']}] {e['count']}")


def reset_cmd(root: str) -> None:
    """#4:清掉本專案全部產物(只碰 .ccodegraph/),逐項印出。"""
    pdir = os.path.join(root, PRODUCTS_DIR)
    if not os.path.isdir(pdir):
        print(f"nothing to reset — {pdir} does not exist")
        return
    import shutil
    for fn in sorted(os.listdir(pdir)):
        print(f"removed {os.path.join(pdir, fn)}")
    shutil.rmtree(pdir)
    print(f"removed {pdir}/ — start over with: ccodegraph.py build -p {root}")


CLI_EPILOG = """\
examples (full reference: ./ccodegraph.py skill):
  ./ccodegraph.py explore <sym> -p .       # def+callers+callees+globals — default first move
  ./ccodegraph.py callers <sym> -p .       # deduped callers; includes [fnptr]/[callback] indirect
  ./ccodegraph.py callees <sym> -p .
  ./ccodegraph.py impact <sym> -d 2 -p .   # change radius
  ./ccodegraph.py who-includes <hdr> -p .  # direct includers, all spelling variants
  ./ccodegraph.py sql "SELECT ... LIMIT 50" -p .
    nodes(name,qname,kind:function|global|macro|file,file,line_start,line_end,signature)
    edges(src,dst,kind:calls|callback|fnptr|reads|writes|includes|expands|co_changes,file,line,meta)
    edge_pairs view(src,dst,kind,first_site,site_count,origins)
  <sym> = name or 'file.c::name' (quote qnames)

token discipline: if the graph exists (.ccodegraph/graph.db) query it directly —
no build/schema/status needed first. Scope sql by file (WHERE e.file LIKE 'src/x%')
instead of bare callers on hot symbols. Outputs cap at 40/section and 200 sql rows
with the TRUE TOTAL always shown (--limit 0 = all). Read cited file:line with a
narrow offset/limit. Cross-check any claimed total with one COUNT(*) query.
config-flag questions: check BOTH in-file #ifdef AND Makefile-level file gating
(ifdef X ... OBJS += foo.o gates whole files that contain no #ifdef at all)."""


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, epilog=CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"ccodegraph {VERSION}")
    ap.add_argument("verb", choices=["build", "clink-import", "schema", "skill",
                                     "status", "reset", "viz", "dumpdb",
                                     "explore", "callers", "callees",
                                     "impact", "globals", "vars-of",
                                     "who-includes", "co-changed", "sql"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("-p", "--root", default=".")
    ap.add_argument("--db")
    ap.add_argument("-d", "--depth", type=int, default=2,
                    help="impact/viz-focus 深度(仿 CodeGraph:預設 2,夾 1-10)")
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--min-conf", type=float, default=DEFAULT_MIN_CONF,
                    help="查詢信心門檻(design §3;預設 0.7)")
    ap.add_argument("--incremental", action="store_true",
                    help="L5:hash 圈變更集,只重掃受影響符號(FR7)")
    ap.add_argument("--compdb", help="逗號分隔的多份 compile_commands.json,"
                    "檔案層級合併(D12;順序=優先權)")
    ap.add_argument("--ambiguous", action="store_true",
                    help="impact 也走 ambiguous 邊(D4 預設不走)")
    ap.add_argument("--format", default="html3d",
                    help="viz:html3d(預設)|html2d")
    ap.add_argument("--focus", help="viz:BFS 聚焦符號(name 或 qname)")
    ap.add_argument("--out", help="viz:輸出檔(預設 .ccodegraph/graph-<dim>.html)")
    ap.add_argument("--module-map",
                    help="R8:module_mapping.csv(regex,module;英文不分大小寫)"
                         "— build 時填 nodes.module,viz 依 module 分群")
    ap.add_argument("--full", action="store_true",
                    help="viz:嵌入全部 8 種邊;status:完整偵錯版"
                         "(全部 env vars/逐項產物/history 5 筆)")
    ap.add_argument("--json", action="store_true",
                    help="FR9:輸出 JSON(與文字欄位一一對應),LLM 自選格式")
    ap.add_argument("--limit", type=int, default=None,
                    help="D16 顯式截斷:callers/callees/explore 每節最多 N 筆"
                         f"(預設 {DEFAULT_LIST_LIMIT});sql 行數上限"
                         f"(預設 {SQL_ROW_CAP})。0=不限;截斷時必印真實總數")
    a = ap.parse_args()
    list_limit = DEFAULT_LIST_LIMIT if a.limit is None else a.limit
    sql_cap = SQL_ROW_CAP if a.limit is None else a.limit
    root = os.path.abspath(a.root)
    db = a.db or os.path.join(root, DB_NAME)

    if a.verb == "skill":
        print(SKILL_MD, end="")   # 內嵌版:單檔 ccodegraph.py 即可輸出 skill
        return None
    if a.verb == "build":
        return build(root, db, a.jobs, a.incremental, a.module_map)
    if a.verb == "clink-import":
        return clink_import(root, db, a.compdb)
    if a.verb == "status":
        res_s = q_status(root, db, a.full)
        if a.json:
            print(json.dumps(res_s, ensure_ascii=False))
        else:
            render_status(res_s, a.full)
        return None
    if a.verb == "reset":
        return reset_cmd(root)
    if a.verb == "viz":
        return viz_cmd(root, db, a.format, a.focus, a.depth, a.out,
                       a.full, a.min_conf)
    if a.verb == "dumpdb":
        if not os.path.exists(db):
            sys.exit(f"ERROR: no graph at {db}")
        res_d = q_dumpdb(db)
        if a.json:
            print(json.dumps(res_d, ensure_ascii=False))
        else:
            render_dumpdb(res_d)
        return None
    if not os.path.exists(db):
        sys.exit(f"ERROR: no graph at {db} — run: ccodegraph.py build -p {root}")
    if a.verb not in ("schema",) and not a.arg:
        sys.exit("ERROR: symbol/SQL required")
    # 查詢一律唯讀連線(codex 高風險 8):sql 逃生口不可變成破壞入口
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    def emit(res: dict[str, Any], render: Any) -> None:
        if a.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            render(res)

    if a.verb == "schema":
        emit(q_schema(con), render_schema)
    elif a.verb == "explore":
        emit(q_explore(con, a.arg, a.min_conf, list_limit), render_explore)
    elif a.verb in ("callers", "callees"):
        emit(q_sectioned(con, a.arg,
                         "dst" if a.verb == "callers" else "src",
                         a.min_conf, list_limit), render_sectioned)
    elif a.verb == "impact":
        starts = node_candidates(con, a.arg, ["function"])
        if not starts:
            sys.exit(f'symbol "{a.arg}" not found')
        dep = max(1, min(10, a.depth))          # 仿 CodeGraph:clamp 1-10
        res: dict[str, Any] = {"verb": "impact", "symbol": a.arg,
                               "depth": dep, "ambiguous": a.ambiguous,
                               "definitions": []}
        for row in starts:
            sid, qname = row[0], row[2]
            depths: dict[str, list[str]] = {}
            by_file: dict[str, list[dict[str, Any]]] = {}
            total = 0
            for depth, qn, nfile, nline in con.execute("""
                WITH RECURSIVE up(id, depth) AS (
                  SELECT :sid, 0
                  UNION
                  SELECT e.src, u.depth+1 FROM
                    (SELECT DISTINCT src,dst FROM edges
                     WHERE kind IN ('calls','fnptr','callback')
                       AND confidence >= :mc
                       AND (:amb OR instr(meta, '"ambiguous"') = 0)) e
                  JOIN up u ON e.dst=u.id WHERE u.depth < :dep)
                SELECT MIN(u.depth), n.qname, n.file, n.line_start
                FROM up u JOIN nodes n ON n.id=u.id WHERE u.depth>0
                GROUP BY n.qname ORDER BY 1, n.qname""",
                    {"sid": sid, "mc": a.min_conf,
                     "amb": int(a.ambiguous), "dep": dep}):
                depths.setdefault(str(depth), []).append(qn)
                by_file.setdefault(nfile, []).append(
                    {"name": qn.rsplit("::", 1)[-1], "line": nline})
                total += 1
            hint = None
            if not depths and not a.ambiguous:
                n_amb = con.execute(
                    "SELECT COUNT(*) FROM edges WHERE dst=? AND "
                    "instr(meta, '\"ambiguous\"') > 0", (sid,)).fetchone()[0]
                if n_amb:
                    hint = (f"no unambiguous impact; {n_amb} ambiguous edges "
                            f"exist — rerun with --ambiguous to include "
                            f"multi-candidate attributions")
            res["definitions"].append(
                {"qname": qname, "affects": total, "depths": depths,
                 "by_file": by_file, "hint": hint})

        def render_impact(res: dict[str, Any]) -> None:
            multi = len(res["definitions"]) > 1
            for d in res["definitions"]:
                print(f"impact of {d['qname']} — affects {d['affects']} "
                      f"symbols (depth <= {res['depth']})")
                for depth, names in d["depths"].items():
                    print(f"depth {depth}: {','.join(names)}")
                if d["by_file"]:
                    print("by file:")
                    for nfile, items in sorted(d["by_file"].items()):
                        inline = ", ".join(
                            f"{it['name']}:{it['line']}" for it in items)
                        print(f"  {nfile}: {inline}")
                if d["hint"]:
                    print(f"({d['hint']})")
                if multi:
                    print()
        emit(res, render_impact)
    elif a.verb == "globals":
        gcands = node_candidates(con, a.arg, ["global"])
        if not gcands:
            sys.exit(f'global "{a.arg}" not found')
        res = {"verb": "globals", "symbol": a.arg, "definitions": []}
        for row in gcands:
            gid, qname = row[0], row[2]
            w = [r[0] for r in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='writes' "
                "AND e.confidence >= ? ORDER BY n.qname", (gid, a.min_conf))]
            r = [x[0] for x in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='reads' "
                "AND e.confidence >= ? ORDER BY n.qname", (gid, a.min_conf))
                if x[0] not in w]
            res["definitions"].append(
                {"qname": qname, "writers": w, "readers": r})

        def render_globals(res: dict[str, Any]) -> None:
            for d in res["definitions"]:
                print(f"writers of {d['qname']} ({len(d['writers'])}):")
                for x in d["writers"]:
                    print(f"  {x}")
                print(f"readers ({len(d['readers'])}):")
                for x in d["readers"]:
                    print(f"  {x}")
        emit(res, render_globals)
    elif a.verb == "vars-of":
        items = [{"qname": qn, "access": kind, "site": f"{f2}:{ln}"}
                 for qn, kind, f2, ln in con.execute(
                     "SELECT n2.qname, e.kind, e.file, e.line FROM edges e "
                     "JOIN nodes n ON n.id=e.src JOIN nodes n2 ON n2.id=e.dst "
                     "WHERE (n.name=? OR n.qname=?) AND e.kind IN "
                     "('reads','writes') AND e.confidence >= ? "
                     "ORDER BY n2.qname, e.kind", (a.arg, a.arg, a.min_conf))]
        res = {"verb": "vars-of", "symbol": a.arg, "items": items}

        def render_varsof(res: dict[str, Any]) -> None:
            for it in res["items"]:
                print(f"{it['qname']}  [{it['access']}]  @ {it['site']}")
        emit(res, render_varsof)
    elif a.verb == "who-includes":
        files = [r[0] for r in con.execute(
            "SELECT DISTINCT e.file FROM edges e JOIN nodes n "
            "ON n.id=e.dst WHERE e.kind='includes' AND "
            "(n.name=? OR n.qname=?) ORDER BY 1", (a.arg, a.arg))]
        res = {"verb": "who-includes", "symbol": a.arg, "files": files}

        def render_inc(res: dict[str, Any]) -> None:
            for f2 in res["files"]:
                print(f2)
        emit(res, render_inc)
    elif a.verb == "co-changed":
        rows = con.execute(
            "SELECT n1.qname, n2.qname, json_extract(e.meta,'$.count') "
            "FROM edges e JOIN nodes n1 ON n1.id=e.src "
            "JOIN nodes n2 ON n2.id=e.dst WHERE e.kind='co_changes' "
            "AND (n1.qname=? OR n2.qname=?) ORDER BY 3 DESC",
            (a.arg, a.arg)).fetchall()
        items = [{"file": (f2 if f1 == a.arg else f1), "count": cnt}
                 for f1, f2, cnt in rows]
        res = {"verb": "co-changed", "symbol": a.arg, "items": items}

        def render_cc(res: dict[str, Any]) -> None:
            if not res["items"]:
                print(f"no co-change data for {res['symbol']}"
                      f"(非 git repo 或共變 < 2 次)")
            for it in res["items"]:
                print(f"{it['file']}  (co-changed {it['count']}x)")
        emit(res, render_cc)
    elif a.verb == "sql":
        run_sql(con, a.arg, sql_cap)


if __name__ == "__main__":
    main()
