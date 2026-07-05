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
import sqlite3
import subprocess
import sys
import time
from typing import Any

VERSION = "0.0.1"

Def = dict[str, Any]          # 節點 dict:name/kind/file/line_start/line_end/is_static/qname/id
CscopeRow = tuple[str, str, int, str]   # (field2, file, line, text)

PRODUCTS_DIR = ".ccodegraph"          # 所有中間產物集中此處(ccq 經驗:不污染使用者空間)
DB_NAME = os.path.join(PRODUCTS_DIR, "graph.db")
CSCOPE_DB = ".ideal-graph.cscope.out"   # 專用索引檔,不污染使用者自己的 cscope.out
HEADER_EXTS = (".h", ".hpp", ".hh")
FANOUT_CAP = 16                          # fnptr field 註冊數上限(超過視為雜訊)
DEFAULT_MIN_CONF = 0.7

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

SCHEMA_SQL = """
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
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_edges_src ON edges(src);
CREATE INDEX idx_edges_dst ON edges(dst);
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


def cscope_lines(root: str, qflag: str, sym: str) -> list[CscopeRow]:
    """cscope -d -f <專用索引> -L<q> sym → [(field2, file, line, text)]。"""
    out: list[CscopeRow] = []
    raw_out = run_checked(
        [tool_path("cscope"), "-d", "-f", CSCOPE_DB, "-L" + qflag, sym], root)
    for raw in raw_out.splitlines():
        p = raw.split(None, 3)
        if len(p) >= 3 and p[2].isdigit():
            out.append((p[1], p[0], int(p[2]), p[3] if len(p) > 3 else ""))
    return out


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
          incremental: bool = False) -> None:
    require_universal_ctags()          # R2:flavor 偵測,非 Universal 大聲死
    try:
        subprocess.run([tool_path("cscope"), "--version"], capture_output=True)
    except FileNotFoundError:
        sys.exit(f"ERROR: cscope not found({tool_path('cscope')})— L1 需要它。"
                 "macOS: brew install cscope / Linux: apt install cscope;"
                 "或設 CCODEGRAPH_CSCOPE_PATH=/path/to/cscope")
    t0 = time.time()
    pdir = os.path.join(root, PRODUCTS_DIR)
    os.makedirs(pdir, exist_ok=True)
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

    print("[L0] cscope index + ctags 節點 …")
    run_checked([tool_path("cscope"), "-bkR", "-f", CSCOPE_DB], root)
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
                "SELECT n1.qname, n1.name, n2.qname, n2.name, e.kind, "
                "e.file, e.line, e.origin, e.confidence, e.meta "
                "FROM edges e JOIN nodes n1 ON n1.id=e.src "
                "JOIN nodes n2 ON n2.id=e.dst "
                "WHERE e.origin IN ('cscope', 'clink')"):
            _sq, sn, _dq, dn, _k, ef, _ln, _o, _c, _m = row
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

    # 原子性重建(codex 高風險 1):寫 temp,成功才 os.replace
    tmp_db = db_path + ".building"
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    con = sqlite3.connect(tmp_db)
    con.executescript(SCHEMA_SQL)
    head = git_head(root)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    con.executemany(
        "INSERT INTO files (path, lang, content_hash, indexed_at, git_rev) "
        "VALUES (?,?,?,?,?)",
        [(p, "c", hashes[p], now, head) for p in srcs])
    for d in defs:
        d["id"] = con.execute(
            "INSERT INTO nodes (name,qname,kind,file,line_start,line_end,"
            "signature,is_static,origin,confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d["qname"], d["kind"], d["file"], d["line_start"],
             d["line_end"], d.get("signature"), int(d["is_static"]), "ctags",
             CONFIDENCE["ctags"])).lastrowid
    file_ids: dict[str, int] = {}
    for p in srcs:
        rowid = con.execute(
            "INSERT INTO nodes (name,qname,kind,file,line_start,line_end,"
            "is_static,origin,confidence) VALUES (?,?,?,?,?,?,0,'ctags',1.0)",
            (os.path.basename(p), p, "file", p, 1, 1)).lastrowid
        assert rowid is not None
        file_ids[p] = rowid

    fn_index: dict[str, list[Def]] = {}
    gv_index: dict[str, list[Def]] = {}
    mc_index: dict[str, list[Def]] = {}
    for d in defs:
        idx = {"function": fn_index, "global": gv_index,
               "macro": mc_index}[str(d["kind"])]
        idx.setdefault(d["name"], []).append(d)

    def add_edge(src_id: int, dst_id: int, kind: str, file: str | None,
                 line: int | None, origin: str, meta: str = "{}") -> None:
        con.execute(
            "INSERT OR IGNORE INTO edges (src,dst,kind,file,line,origin,"
            "confidence,meta) VALUES (?,?,?,?,?,?,?,?)",
            (src_id, dst_id, kind, file, line, origin,
             CONFIDENCE[origin], meta))

    if incremental:
        qid = {q: i for q, i in con.execute(
            "SELECT qname, id FROM nodes")}
        n_kept = 0
        for sq, _sn, dq, _dn, k, ef, ln, o, c, m in kept_edges:
            si, di = qid.get(sq), qid.get(dq)
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
    print(f"[L1] cscope 邊:calls(-dL3)x{len(fn_names)} + "
          f"reads/writes x{len(gv_names)} + includes,{jobs} workers …")
    all_headers = [p for p in srcs if p.endswith(HEADER_EXTS)]
    base_count: dict[str, int] = {}
    for h in all_headers:
        base_count[os.path.basename(h)] = base_count.get(os.path.basename(h), 0) + 1
    headers = sorted(aff_headers) if incremental else all_headers
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        # calls:對每個函式名問「誰呼叫它」(-dL3;-dL2 會漏巢狀內層呼叫)
        callers_of = ex.map(lambda n: cscope_lines(root, "3", n), fn_names)
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
        refs_of = ex.map(lambda n: cscope_lines(root, "0", n), gv_names)
        writes_of = ex.map(lambda n: cscope_lines(root, "9", n), gv_names)
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
        users_of = ex.map(lambda n: cscope_lines(root, "3", n), mc_names)
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
        includers = ex.map(
            lambda h: cscope_lines(root, "8", os.path.basename(h)), headers)
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
    cdb = os.path.join(root, PRODUCTS_DIR, "clink.db")
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
    mode_file = os.path.join(pdir, "clink_mode.txt")
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
            path = os.path.relpath(path, root)
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
        f" AND e.{other}=p.{other} AND e.kind=p.kind LIMIT 1) "
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


def q_sectioned(con: sqlite3.Connection, sym: str, direction: str,
                min_conf: float) -> dict[str, Any]:
    cands = node_candidates(con, sym, ["function", "macro"])
    verb = "callers" if direction == "dst" else "callees"
    res: dict[str, Any] = {"verb": verb, "symbol": sym,
                           "min_conf": min_conf, "definitions": []}
    for cid, _n, qname, kind, file, line, _st, sig in cands:
        res["definitions"].append({
            "qname": qname, "kind": kind, "file": file, "line": line,
            "signature": sig,
            "items": pair_items(con, cid, direction, QUERY_KINDS, min_conf)})
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
        if len(defs) > 1:
            print()


def q_explore(con: sqlite3.Connection, sym: str,
              min_conf: float) -> dict[str, Any]:
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
        res["definitions"].append({
            "qname": qname, "file": file, "line": line, "signature": sig,
            "callers": pair_items(con, cid, "dst", QUERY_KINDS, min_conf),
            "callees": [x for x in callees_all
                        if "expands" not in x["origins"] or True],
            "globals": [{"qname": g, "access": k, "site": f"{gf}:{gl_}"}
                        for g, k, gf, gl_ in gl],
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
        print(f"callers ({len(d['callers'])}):")
        for it in d["callers"]:
            print("  " + fmt_item(it))
        print(f"callees ({len(d['callees'])}):")
        for it in d["callees"]:
            print("  " + fmt_item(it))
        print(f"globals ({len(d['globals'])}):")
        for g in d["globals"]:
            print(f"  - {g['qname']}  [{g['access']}]  @ {g['site']}")
        print()


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


def q_status(root: str, db: str) -> dict[str, Any]:
    """#4 維護動詞(ccq status 血統):環境/skill/產物/出處/新鮮度,路徑全印。"""
    res: dict[str, Any] = {"verb": "status", "root": root}
    tools = {}
    for t in ("ctags", "cscope", "clink", "git"):
        p = tool_path(t) if t != "clink" else CLINK_BIN
        try:
            r = subprocess.run([p, "--version"], capture_output=True, text=True)
            ver = (r.stdout or r.stderr).splitlines()[0].strip() if \
                (r.stdout or r.stderr) else "?"
        except FileNotFoundError:
            ver = "not found"
        env = f"CCODEGRAPH_{t.upper()}_PATH"
        tools[t] = {"path": p, "version": ver,
                    "env_override": env in os.environ
                    or (t == "clink" and "CCODEGRAPH_CLINK" in os.environ)}
    res["tools"] = tools
    found = [os.path.expanduser(d) for d in SKILL_INSTALL_DIRS
             if os.path.exists(os.path.join(os.path.expanduser(d), "SKILL.md"))]
    res["skill"] = {"installed": found,
                    "hint": None if found else
                    "ccodegraph.py skill > ~/.claude/skills/ccodegraph/SKILL.md"}
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
    if not os.path.exists(db):
        res["artifact"] = None
        res["suggestion"] = f"no graph — run: ccodegraph.py build -p {root}"
        return res
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    art: dict[str, Any] = {
        "schema_version": meta.get("schema_version"),
        "engines_run": json.loads(meta.get("engines_run", "[]")),
        "nodes": con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": con.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
    }
    row = con.execute("SELECT git_rev FROM files WHERE git_rev IS NOT NULL "
                      "LIMIT 1").fetchone()
    art["built_at_git"] = row[0][:12] if row and row[0] else None
    res["artifact"] = art
    head = git_head(root)
    res["git_now"] = head[:12] if head else None
    old_hashes = dict(con.execute(
        "SELECT path, content_hash FROM files WHERE content_hash IS NOT NULL"))
    con.close()
    srcs = source_files(root)
    new_hashes = {p: file_hash(os.path.join(root, p)) for p in srcs}
    changed, added, deleted = compute_changes(old_hashes, new_hashes)
    drift = sorted(changed | added | deleted)
    res["drift"] = {"changed": len(changed), "added": len(added),
                    "deleted": len(deleted), "files": drift[:5]}
    res["suggestion"] = (
        f"{len(drift)} file(s) differ from the graph — run: "
        f"ccodegraph.py build --incremental -p {root}" if drift
        else "graph is aligned with the source tree")
    return res


def render_status(res: dict[str, Any]) -> None:
    print(f"ccodegraph status — {res['root']}")
    print("tools:")
    for t, info in res["tools"].items():
        ov = "  (env override)" if info["env_override"] else ""
        print(f"  {t:7s} {info['path']}  —  {info['version']}{ov}")
    sk = res["skill"]
    if sk["installed"]:
        print("skill  : " + "; ".join(sk["installed"]))
    else:
        print(f"skill  : not installed — {sk['hint']}")
    print("products:")
    for p in res["products"]:
        print(f"  {p['path']}  {p['size']:,} B  {p['mtime']}")
    if not res["products"]:
        print("  (none)")
    art = res.get("artifact")
    if art:
        print(f"artifact: schema v{art['schema_version']}, "
              f"{art['nodes']} nodes, {art['edges']} edges")
        for e in art["engines_run"]:
            print(f"  engine: {e}")
        if art.get("built_at_git"):
            print(f"  built at git {art['built_at_git']}"
                  + (f"; now {res['git_now']}" if res.get("git_now") else ""))
        d = res["drift"]
        if d["files"]:
            print(f"drift  : changed={d['changed']} added={d['added']} "
                  f"deleted={d['deleted']}: {', '.join(d['files'])}"
                  + (" …" if d["changed"] + d["added"] + d["deleted"] > 5 else ""))
    print(f"→ {res['suggestion']}")


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="version",
                    version=f"ccodegraph {VERSION}")
    ap.add_argument("verb", choices=["build", "clink-import", "schema", "skill",
                                     "status", "reset", "viz",
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
    ap.add_argument("--full", action="store_true",
                    help="viz:嵌入全部 8 種邊(預設只嵌呼叫家族)")
    ap.add_argument("--json", action="store_true",
                    help="FR9:輸出 JSON(與文字欄位一一對應),LLM 自選格式")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    db = a.db or os.path.join(root, DB_NAME)

    if a.verb == "skill":
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "skills", "ccodegraph", "SKILL.md")
        try:
            with open(p) as fh:
                print(fh.read(), end="")
        except OSError:
            sys.exit(f"ERROR: SKILL.md not found at {p}")
        return None
    if a.verb == "build":
        return build(root, db, a.jobs, a.incremental)
    if a.verb == "clink-import":
        return clink_import(root, db, a.compdb)
    if a.verb == "status":
        res_s = q_status(root, db)
        if a.json:
            print(json.dumps(res_s, ensure_ascii=False))
        else:
            render_status(res_s)
        return None
    if a.verb == "reset":
        return reset_cmd(root)
    if a.verb == "viz":
        return viz_cmd(root, db, a.format, a.focus, a.depth, a.out,
                       a.full, a.min_conf)
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
        emit(q_explore(con, a.arg, a.min_conf), render_explore)
    elif a.verb in ("callers", "callees"):
        emit(q_sectioned(con, a.arg,
                         "dst" if a.verb == "callers" else "src",
                         a.min_conf), render_sectioned)
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
        for row2 in con.execute(a.arg):
            print("|".join(str(c) for c in row2))


if __name__ == "__main__":
    main()
