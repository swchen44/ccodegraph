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
    "clangd-nobuild": 0.75,
    "callback": 0.70,
    "git": 0.50,
}

# schema 動詞回報「格子還空著」用(design.md §5 填料計畫)
PENDING_LAYERS: list[tuple[str, str]] = [
    ("treesitter", "L2: calls 聯集補充、K&R defs"),
    ("fnptr", "L3: ops/vtable 分派邊 + manual 表"),
    ("callback", "L3: fn-as-argument 邊"),
    ("clangd", "L4: 高信心 calls/uses_type/signature 升級(需 compile DB)"),
    ("git", "L5: co_changes 邊 + 增量失效"),
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


# ---------------------------------------------------------------- 外部工具層

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
        ["cscope", "-d", "-f", CSCOPE_DB, "-L" + qflag, sym], root)
    for raw in raw_out.splitlines():
        p = raw.split(None, 3)
        if len(p) >= 3 and p[2].isdigit():
            out.append((p[1], p[0], int(p[2]), p[3] if len(p) > 3 else ""))
    return out


def ctags_defs(root: str) -> list[Def]:
    """L0:ctags JSON → 節點原料。kind: function|global(ctags f/v);
    static 用定義行文字偵測(近似,documented)。"""
    out = run_checked(["ctags", "-R", "--languages=C,C++",
                       "--kinds-C=f,v", "--kinds-C++=f,v",
                       "--fields=+ne", "--output-format=json", "."], root)
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
        kind = {"function": "function", "variable": "global"}.get(o.get("kind", ""))
        if not kind:
            continue
        defs.append({
            "name": o["name"], "kind": kind, "file": path,
            "line_start": line, "line_end": int(o.get("end", line)),
            "is_static": detect_static(src_cache[path], line),
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


def build(root: str, db_path: str, jobs: int) -> None:
    for tool in ("cscope", "ctags"):
        try:
            subprocess.run([tool, "--version"], capture_output=True)
        except FileNotFoundError:
            sys.exit(f"ERROR: {tool} not found — L0/L1 需要它(NFR1)")
    t0 = time.time()
    pdir = os.path.join(root, PRODUCTS_DIR)
    os.makedirs(pdir, exist_ok=True)
    gi = os.path.join(pdir, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as fh:
            fh.write("*\n")           # 產物永不進使用者的版控(ccq 經驗)

    print("[L0] cscope index + ctags 節點 …")
    run_checked(["cscope", "-bkR", "-f", CSCOPE_DB], root)
    defs = assign_qnames(ctags_defs(root))
    srcs = source_files(root)
    n_fn = sum(1 for d in defs if d["kind"] == "function")
    n_gv = sum(1 for d in defs if d["kind"] == "global")
    print(f"     {n_fn} functions, {n_gv} globals, {len(srcs)} files")

    # 原子性重建(codex 高風險 1):寫 temp,成功才 os.replace
    tmp_db = db_path + ".building"
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    con = sqlite3.connect(tmp_db)
    con.executescript(SCHEMA_SQL)
    con.executemany("INSERT INTO files (path, lang) VALUES (?,?)",
                    [(p, "c") for p in srcs])
    for d in defs:
        d["id"] = con.execute(
            "INSERT INTO nodes (name,qname,kind,file,line_start,line_end,"
            "is_static,origin,confidence) VALUES (?,?,?,?,?,?,?,?,?)",
            (d["name"], d["qname"], d["kind"], d["file"], d["line_start"],
             d["line_end"], int(d["is_static"]), "ctags",
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
    for d in defs:
        (fn_index if d["kind"] == "function" else gv_index) \
            .setdefault(d["name"], []).append(d)

    def add_edge(src_id: int, dst_id: int, kind: str, file: str, line: int,
                 origin: str, meta: str = "{}") -> None:
        con.execute(
            "INSERT OR IGNORE INTO edges (src,dst,kind,file,line,origin,"
            "confidence,meta) VALUES (?,?,?,?,?,?,?,?)",
            (src_id, dst_id, kind, file, line, origin,
             CONFIDENCE[origin], meta))

    fn_names = sorted(fn_index)
    gv_names = sorted(gv_index)
    print(f"[L1] cscope 邊:calls(-dL3)x{len(fn_names)} + "
          f"reads/writes x{len(gv_names)} + includes,{jobs} workers …")
    headers = [p for p in srcs if p.endswith(HEADER_EXTS)]
    base_count: dict[str, int] = {}
    for h in headers:
        base_count[os.path.basename(h)] = base_count.get(os.path.basename(h), 0) + 1
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

    con.execute("INSERT INTO meta VALUES ('schema_version','1')")
    con.execute("INSERT INTO meta VALUES ('root',?)", (root,))
    con.execute("INSERT INTO meta VALUES ('engines_run',?)",
                (json.dumps([{"engine": "ctags+cscope+heuristics",
                              "layers": "L0+L1+L3",
                              "seconds": round(time.time() - t0, 1)}]),))
    con.commit()
    counts = dict(con.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind"))
    con.close()
    os.replace(tmp_db, db_path)          # 原子切換
    print(f"done: {db_path}  ({len(defs) + len(srcs)} nodes; edges: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f"; {time.time() - t0:.0f}s)")
    print("note: L2(treesitter)/L4(clangd)/L5(git)尚未填 — "
          "`schema` 動詞會列出空格子。")


# ---------------------------------------------------------------- 查詢動詞

def fmt_site(padded: str | None) -> str:
    """edge_pairs.first_site 是 printf('%s:%09d') 的可排序形式 → 還原顯示。"""
    if not padded:
        return "?"
    f, _, n = padded.rpartition(":")
    return f"{f}:{int(n)}" if n.isdigit() else padded


def fmt_tags(origins: str, meta_json: str | None) -> str:
    tags = [origins]
    try:
        m: dict[str, Any] = json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        m = {}
    if m.get("ambiguous"):
        tags.append(f'ambiguous {m.get("candidates", "?")} candidates')
    if "clangd" in m:
        tags.append(f'clangd:{m["clangd"]}')
    return "[" + "; ".join(tags) + "]"


def node_candidates(con: sqlite3.Connection, sym: str,
                    kinds: list[str]) -> list[tuple[Any, ...]]:
    ph = ",".join("?" * len(kinds))
    return con.execute(
        f"SELECT id,name,qname,kind,file,line_start,is_static FROM nodes "
        f"WHERE (name=? OR qname=?) AND kind IN ({ph}) ORDER BY file",
        (sym, sym, *kinds)).fetchall()


def sectioned(con: sqlite3.Connection, sym: str, direction: str,
              min_conf: float) -> None:
    """callers/callees:同名多定義 → 分節(D1);ambiguous 邊照 D4 顯示 + 標籤。"""
    cands = node_candidates(con, sym, ["function"])
    if not cands:
        print(f'symbol "{sym}" not found (kind=function)')
        return
    if len(cands) > 1:
        print(f"{('callers' if direction == 'dst' else 'callees')} of {sym} "
              f"— {len(cands)} definitions(分節;可用 qname 精確指定):\n")
    other = "src" if direction == "dst" else "dst"
    for cid, _n, qname, _k, file, line, _st in cands:
        if len(cands) > 1:
            print(f"## {qname} 的定義 @ {file}:{line}")
        rows = con.execute(
            f"SELECT n.qname, p.first_site, p.site_count, p.origins, "
            f"(SELECT meta FROM edges e WHERE e.{direction}=p.{direction} "
            f" AND e.{other}=p.{other} AND e.kind=p.kind LIMIT 1) "
            f"FROM edge_pairs p JOIN nodes n ON n.id=p.{other} "
            f"WHERE p.{direction}=? AND p.kind IN "
            f"('calls','fnptr','callback') AND p.confidence >= ? "
            f"ORDER BY n.qname", (cid, min_conf)).fetchall()
        if not rows:
            print("- (none)")
        for qn, site, nsites, origins, meta in rows:
            extra = f" ({nsites} sites)" if nsites > 1 else ""
            print(f"- {qn}  @ {fmt_site(site)}{extra}  {fmt_tags(origins, meta)}")
        if len(cands) > 1:
            print()


def cmd_schema(con: sqlite3.Connection) -> None:
    print("nodes:")
    for kind, cnt in con.execute(
            "SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY kind"):
        print(f"  {kind:10s} {cnt}")
    print("edges (kind x origin):")
    for kind, origin, cnt in con.execute(
            "SELECT kind, origin, COUNT(*) FROM edges "
            "GROUP BY kind, origin ORDER BY kind"):
        print(f"  {kind:10s} [{origin}] {cnt}")
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
            print("WARNING: fnptr.json changed since build — manual edges are "
                  "STALE; re-run build")
        elif stored and cur is None:
            print("WARNING: fnptr.json deleted since build — manual edges are "
                  "STALE; re-run build")
        elif cur and not stored:
            print("note: fnptr.json present but not in this graph — re-run "
                  "build to ingest it")
    filled = {r[0] for r in con.execute("SELECT DISTINCT origin FROM edges")}
    print("pending(空格子,design §5):")
    for origin, desc in PENDING_LAYERS:
        if origin not in filled:
            print(f"  {origin:12s} {desc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("verb", choices=["build", "schema", "callers", "callees",
                                     "impact", "globals", "vars-of",
                                     "who-includes", "sql"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("-p", "--root", default=".")
    ap.add_argument("--db")
    ap.add_argument("-d", "--depth", type=int, default=3)
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--min-conf", type=float, default=DEFAULT_MIN_CONF,
                    help="查詢信心門檻(design §3;預設 0.7)")
    ap.add_argument("--ambiguous", action="store_true",
                    help="impact 也走 ambiguous 邊(D4 預設不走)")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    db = a.db or os.path.join(root, DB_NAME)

    if a.verb == "build":
        return build(root, db, a.jobs)
    if not os.path.exists(db):
        sys.exit(f"ERROR: no graph at {db} — run: ccodegraph.py build -p {root}")
    if a.verb not in ("schema",) and not a.arg:
        sys.exit("ERROR: symbol/SQL required")
    # 查詢一律唯讀連線(codex 高風險 8):sql 逃生口不可變成破壞入口
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    if a.verb == "schema":
        cmd_schema(con)
    elif a.verb == "callers":
        sectioned(con, a.arg, "dst", a.min_conf)
    elif a.verb == "callees":
        sectioned(con, a.arg, "src", a.min_conf)
    elif a.verb == "impact":
        starts = [r[0] for r in node_candidates(con, a.arg, ["function"])]
        if not starts:
            sys.exit(f'symbol "{a.arg}" not found')
        for sid in starts:
            for depth, names in con.execute("""
                WITH RECURSIVE up(id, depth) AS (
                  SELECT :sid, 0
                  UNION
                  SELECT e.src, u.depth+1 FROM
                    (SELECT DISTINCT src,dst FROM edges
                     WHERE kind IN ('calls','fnptr','callback')
                       AND confidence >= :mc
                       AND (:amb OR instr(meta, '"ambiguous"') = 0)) e
                  JOIN up u ON e.dst=u.id WHERE u.depth < :dep)
                SELECT u.depth, GROUP_CONCAT(DISTINCT n.qname)
                FROM up u JOIN nodes n ON n.id=u.id WHERE u.depth>0
                GROUP BY u.depth ORDER BY u.depth""",
                    {"sid": sid, "mc": a.min_conf,
                     "amb": int(a.ambiguous), "dep": a.depth}):
                print(f"depth {depth}: {names}")
    elif a.verb == "globals":
        gcands = node_candidates(con, a.arg, ["global"])
        if not gcands:
            sys.exit(f'global "{a.arg}" not found')
        for gid, _n, qname, *_rest in gcands:
            w = [r[0] for r in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='writes' "
                "AND e.confidence >= ? ORDER BY n.qname", (gid, a.min_conf))]
            r = [x[0] for x in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='reads' "
                "AND e.confidence >= ? ORDER BY n.qname", (gid, a.min_conf))
                if x[0] not in w]
            print(f"writers of {qname} ({len(w)}):")
            for s in w:
                print(f"  {s}")
            print(f"readers ({len(r)}):")
            for s in r:
                print(f"  {s}")
    elif a.verb == "vars-of":
        for qn, kind, f, ln in con.execute(
                "SELECT n2.qname, e.kind, e.file, e.line FROM edges e "
                "JOIN nodes n ON n.id=e.src JOIN nodes n2 ON n2.id=e.dst "
                "WHERE (n.name=? OR n.qname=?) AND e.kind IN "
                "('reads','writes') AND e.confidence >= ? "
                "ORDER BY n2.qname, e.kind", (a.arg, a.arg, a.min_conf)):
            print(f"{qn}  [{kind}]  @ {f}:{ln}")
    elif a.verb == "who-includes":
        for (src_file,) in con.execute(
                "SELECT DISTINCT e.file FROM edges e JOIN nodes n "
                "ON n.id=e.dst WHERE e.kind='includes' AND "
                "(n.name=? OR n.qname=?) ORDER BY 1", (a.arg, a.arg)):
            print(src_file)
    elif a.verb == "sql":
        for row in con.execute(a.arg):
            print("|".join(str(c) for c in row))


if __name__ == "__main__":
    main()
