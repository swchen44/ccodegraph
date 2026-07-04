#!/usr/bin/env python3
"""idealgraph — 理想 C 知識圖譜:多引擎分層填料、逐筆標注 origin/confidence。

Python 標準庫 only。外部 binary:cscope、universal-ctags(L0/L1);
後續層(tree-sitter/clangd/git)缺工具時明講跳過,不靜默(NFR1/P7)。

Schema 與決策見 docs/design.md;本檔實作 L0(ctags 節點)+ L1(cscope 邊)
與查詢動詞。歸戶規則(D1):src 用行區間精確判定;dst 先套 static 同檔規則,
殘餘非 static 同名 → 一對多掛靠 + ambiguous 註記(D3)。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Any

Def = dict[str, Any]          # 節點 dict:name/kind/file/line_start/line_end/is_static/qname/id
CscopeRow = tuple[str, str, int]   # (field2, file, line)

DB_NAME = ".ideal-graph.db"

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
         MIN(file || ':' || line) AS first_site,
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


def detect_static(lines: list[str], line_no: int) -> bool:
    """定義行或其上一行含 `static` token(K&R 換行式)。lines 為 0-based list。"""
    for ln in (line_no - 1, line_no - 2):
        if 0 <= ln < len(lines) and STATIC_RE.search(lines[ln]):
            return True
    return False


def assign_qnames(defs: list[Def]) -> list[Def]:
    """D1 消歧名:static → `file::name`;非 static 同名多定義 → 全部 `file::name`;
    同檔仍撞名(#ifdef 分支各定義一次)→ 再加 `:line`;其餘 → `name`。
    就地寫入每個 def 的 'qname'。"""
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
    """src 歸戶(D1,精確優先):
    1) 同名 + 同檔 + line 落在 [line_start, line_end] → 判定
    2) 同名 + 同檔唯一(ctags 缺 end 的 fallback)
    3) 全域唯一同名
    否則 None(寧可漏報)。"""
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
    """dst 歸戶(D1):static 只可能被同檔呼叫(C 語意)→ 先剔除異檔 static;
    回傳 viable list——len==1 是判定,>1 掛全部並標 ambiguous(D3),0 放棄。"""
    return [c for c in cands if not c["is_static"] or c["file"] == site_file]


def edge_meta(viable_count: int, extra: dict[str, Any] | None = None) -> str:
    """D3 註記:非 static 同名一對多掛靠時標 ambiguous。"""
    m: dict[str, Any] = dict(extra or {})
    if viable_count > 1:
        m.update({"ambiguous": True, "candidates": viable_count,
                  "rule": "non-static-dup"})
    return json.dumps(m, sort_keys=True) if m else "{}"


# ---------------------------------------------------------------- 外部工具層

def run(cmd: list[str], cwd: str) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


def cscope_lines(root: str, qflag: str, sym: str) -> list[CscopeRow]:
    """cscope -dL<q> sym → [(field2, file, line)];格式壞列丟棄。"""
    out: list[CscopeRow] = []
    for raw in run(["cscope", "-dL" + qflag, sym], root).splitlines():
        p = raw.split(None, 3)
        if len(p) >= 3 and p[2].isdigit():
            out.append((p[1], p[0], int(p[2])))
    return out


def ctags_defs(root: str) -> list[Def]:
    """L0:ctags JSON → [{name, kind, file, line_start, line_end, is_static}]。
    kind: function|global(ctags f/v)。static 用定義行文字偵測(近似,見 design)。"""
    out = run(["ctags", "-R", "--languages=C,C++",
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

def build(root: str, db_path: str, jobs: int) -> None:
    for tool in ("cscope", "ctags"):
        try:
            subprocess.run([tool, "--version"], capture_output=True)
        except FileNotFoundError:
            sys.exit(f"ERROR: {tool} not found — L0/L1 需要它(NFR1)")
    t0 = time.time()

    print("[L0] cscope index + ctags 節點 …")
    subprocess.run(["cscope", "-bkR"], cwd=root, check=True)
    defs = assign_qnames(ctags_defs(root))
    srcs = source_files(root)
    n_fn = sum(1 for d in defs if d["kind"] == "function")
    n_gv = sum(1 for d in defs if d["kind"] == "global")
    print(f"     {n_fn} functions, {n_gv} globals, {len(srcs)} files")

    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
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
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        # calls:對每個函式名問「誰呼叫它」(-dL3;-dL2 會漏巢狀內層呼叫)
        callers_of = ex.map(lambda n: cscope_lines(root, "3", n), fn_names)
        for name, rows in zip(fn_names, callers_of, strict=True):
            for caller, f, ln in rows:
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
        # reads/writes:reads = L0 站點 - L9 站點(design §2 狀態家族)
        refs_of = ex.map(lambda n: cscope_lines(root, "0", n), gv_names)
        writes_of = ex.map(lambda n: cscope_lines(root, "9", n), gv_names)
        for name, refs, writes in zip(gv_names, refs_of, writes_of, strict=True):
            wsites = {(f, ln) for _fn, f, ln in writes}
            for kind, rows in (("writes", writes), ("reads", refs)):
                for fn, f, ln in rows:
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
        # includes:file → file(cscope -dL8,C 獨有的直接訊號)
        headers = [p for p in srcs if p.endswith((".h", ".hpp"))]
        includers = ex.map(
            lambda h: cscope_lines(root, "8", os.path.basename(h)), headers)
        for hdr, rows in zip(headers, includers, strict=True):
            for _f2, f, ln in rows:
                if f in file_ids and f != hdr:
                    add_edge(file_ids[f], file_ids[hdr], "includes", f, ln,
                             "cscope")

    con.execute("INSERT INTO meta VALUES ('schema_version','1')")
    con.execute("INSERT INTO meta VALUES ('root',?)", (root,))
    con.execute("INSERT INTO meta VALUES ('engines_run',?)",
                (json.dumps([{"engine": "ctags+cscope", "layer": "L0+L1",
                              "seconds": round(time.time() - t0, 1)}]),))
    con.commit()
    counts = dict(con.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind"))
    print(f"done: {db_path}  ({len(defs) + len(srcs)} nodes; edges: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f"; {time.time() - t0:.0f}s)")
    print("note: L2-L5(treesitter/fnptr/callback/clangd/git)尚未填 — "
          "`schema` 動詞會列出空格子。")


# ---------------------------------------------------------------- 查詢動詞

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


def sectioned(con: sqlite3.Connection, sym: str, direction: str) -> None:
    """callers/callees:同名多定義 → 分節(D1)。direction: 'dst'=callers。"""
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
            f"('calls','fnptr','callback') ORDER BY n.qname", (cid,)).fetchall()
        if not rows:
            print("- (none)")
        for qn, site, nsites, origins, meta in rows:
            extra = f" ({nsites} sites)" if nsites > 1 else ""
            print(f"- {qn}  @ {site}{extra}  {fmt_tags(origins, meta)}")
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
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    db = a.db or os.path.join(root, DB_NAME)

    if a.verb == "build":
        return build(root, db, a.jobs)
    if not os.path.exists(db):
        sys.exit(f"ERROR: no graph at {db} — run: idealgraph.py build -p {root}")
    if a.verb not in ("schema",) and not a.arg:
        sys.exit("ERROR: symbol/SQL required")
    con = sqlite3.connect(db)

    if a.verb == "schema":
        cmd_schema(con)
    elif a.verb == "callers":
        sectioned(con, a.arg, "dst")
    elif a.verb == "callees":
        sectioned(con, a.arg, "src")
    elif a.verb == "impact":
        starts = [r[0] for r in node_candidates(con, a.arg, ["function"])]
        if not starts:
            sys.exit(f'symbol "{a.arg}" not found')
        for sid in starts:
            for depth, names in con.execute("""
                WITH RECURSIVE up(id, depth) AS (
                  SELECT ?, 0
                  UNION
                  SELECT e.src, u.depth+1 FROM
                    (SELECT DISTINCT src,dst FROM edges
                     WHERE kind IN ('calls','fnptr','callback')) e
                  JOIN up u ON e.dst=u.id WHERE u.depth < ?)
                SELECT u.depth, GROUP_CONCAT(DISTINCT n.qname)
                FROM up u JOIN nodes n ON n.id=u.id WHERE u.depth>0
                GROUP BY u.depth ORDER BY u.depth""", (sid, a.depth)):
                print(f"depth {depth}: {names}")
    elif a.verb == "globals":
        gcands = node_candidates(con, a.arg, ["global"])
        if not gcands:
            sys.exit(f'global "{a.arg}" not found')
        for gid, _n, qname, *_rest in gcands:
            w = [r[0] for r in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='writes' "
                "ORDER BY n.qname", (gid,))]
            r = [x[0] for x in con.execute(
                "SELECT DISTINCT n.qname FROM edges e JOIN nodes n "
                "ON n.id=e.src WHERE e.dst=? AND e.kind='reads' "
                "ORDER BY n.qname", (gid,)) if x[0] not in w]
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
                "('reads','writes') ORDER BY n2.qname, e.kind",
                (a.arg, a.arg)):
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
