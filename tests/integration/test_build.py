"""Integration tests — 在 miniproj fixture 上真跑 cscope+ctags 建圖,
驗 schema 內容:D1 消歧、D3 註記、reads/writes、includes。
缺 cscope/ctags 時 skip 並明講(NFR4)。"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

import ccodegraph as ig

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "miniproj")


def tools_ok():
    if not (shutil.which("cscope") and shutil.which("ctags")):
        return False
    v = subprocess.run(["ctags", "--version"], capture_output=True, text=True)
    return "Universal Ctags" in v.stdout


@unittest.skipUnless(tools_ok(), "needs cscope + universal-ctags on PATH")
class TestBuildMiniproj(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "miniproj")
        shutil.copytree(FIXTURE, cls.root)
        cls.db = os.path.join(cls.root, ig.DB_NAME)
        ig.build(cls.root, cls.db, jobs=4)
        cls.con = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.tmp)

    def qname_id(self, qname):
        row = self.con.execute(
            "SELECT id FROM nodes WHERE qname=?", (qname,)).fetchone()
        self.assertIsNotNone(row, f"node {qname} missing")
        return row[0]

    def pairs(self, kind):
        return set(self.con.execute(
            "SELECT n1.qname, n2.qname FROM edges e "
            "JOIN nodes n1 ON n1.id=e.src JOIN nodes n2 ON n2.id=e.dst "
            "WHERE e.kind=?", (kind,)))

    # ---- L0 nodes / D1 qname ----

    def test_static_dup_gets_qualified_qnames(self):
        qnames = {r[0] for r in self.con.execute(
            "SELECT qname FROM nodes WHERE name='helper'")}
        self.assertEqual(qnames, {"util.c::helper", "main.c::helper"})

    def test_nonstatic_dup_gets_qualified_qnames(self):
        qnames = {r[0] for r in self.con.execute(
            "SELECT qname FROM nodes WHERE name='app_init'")}
        self.assertEqual(qnames,
                         {"alt_init.c::app_init", "alt_init2.c::app_init"})

    def test_unique_symbols_plain_qname(self):
        for q in ("add", "main", "use_helper", "counter"):
            self.qname_id(q)

    def test_global_node_kind(self):
        kind = self.con.execute(
            "SELECT kind FROM nodes WHERE qname='counter'").fetchone()[0]
        self.assertEqual(kind, "global")

    # ---- L1 calls / D1 dst 歸戶 ----

    def test_static_same_file_rule(self):
        calls = self.pairs("calls")
        self.assertIn(("use_helper", "util.c::helper"), calls)
        self.assertIn(("main", "main.c::helper"), calls)
        # 反向污染必須為零:static 不可跨檔
        self.assertNotIn(("use_helper", "main.c::helper"), calls)
        self.assertNotIn(("main", "util.c::helper"), calls)

    def test_direct_call_unique_dst(self):
        self.assertIn(("main", "add"), self.pairs("calls"))

    def test_nonstatic_dup_attached_to_all_with_ambiguous_meta(self):
        calls = self.pairs("calls")
        self.assertIn(("do_start", "alt_init.c::app_init"), calls)
        self.assertIn(("do_start", "alt_init2.c::app_init"), calls)
        metas = [json.loads(m) for (m,) in self.con.execute(
            "SELECT e.meta FROM edges e JOIN nodes n2 ON n2.id=e.dst "
            "WHERE n2.name='app_init'")]
        for m in metas:
            self.assertTrue(m.get("ambiguous"), m)
            self.assertEqual(m.get("candidates"), 2)

    def test_edges_carry_site_and_confidence(self):
        f, ln, conf = self.con.execute(
            "SELECT e.file, e.line, e.confidence FROM edges e "
            "JOIN nodes n2 ON n2.id=e.dst WHERE n2.qname='add' "
            "AND e.kind='calls'").fetchone()
        self.assertEqual(f, "main.c")
        self.assertGreater(ln, 0)
        self.assertEqual(conf, ig.CONFIDENCE["cscope"])

    # ---- L1 reads/writes ----

    def test_writes_edge(self):
        self.assertIn(("main", "counter"), self.pairs("writes"))

    def test_reads_edge_excludes_write_sites(self):
        reads = self.pairs("reads")
        self.assertIn(("get_counter", "counter"), reads)
        self.assertNotIn(("main", "counter"), reads)   # 該站點是 write

    # ---- L1 includes + file 投影 ----

    def test_includes_edges(self):
        inc = self.pairs("includes")
        self.assertIn(("util.c", "util.h"), inc)
        self.assertIn(("main.c", "util.h"), inc)

    def test_file_deps_view(self):
        deps = set(self.con.execute(
            "SELECT src_file, dst_file FROM file_deps WHERE kind='calls'"))
        self.assertIn(("main.c", "util.c"), deps)   # main 呼叫 util.c 的 add

    # ---- L3 callback / fnptr / manual ----

    def test_callback_edge(self):
        cb = self.pairs("callback")
        self.assertIn(("sort_things", "callback.c::cmp"), cb)

    def test_string_fake_call_no_edge(self):
        # 字串內的 "cmp(x)" 不得造任何邊(12 場景 string_fake_call 防線)
        for kind in ("callback", "calls"):
            self.assertNotIn(("log_fake", "callback.c::cmp"),
                             self.pairs(kind))

    def test_fnptr_dispatch_edge(self):
        self.assertIn(("dispatch_op", "ops.c::impl_run"), self.pairs("fnptr"))

    def test_manual_registration_edge(self):
        # FR3:registrations(struct/field → handler)→ 分派站點射 manual 邊
        row = self.con.execute(
            "SELECT e.file, e.line, e.meta, e.confidence FROM edges e "
            "JOIN nodes n1 ON n1.id=e.src JOIN nodes n2 ON n2.id=e.dst "
            "WHERE n1.name='dispatch_op' AND n2.name='extra_handler' "
            "AND e.origin='manual' AND e.file != '(manual)'").fetchone()
        self.assertIsNotNone(row, "registration-driven manual edge missing")
        f, ln, meta, conf = row
        self.assertEqual(f, "ops.c")
        self.assertGreater(ln, 0)
        m = json.loads(meta)
        self.assertEqual(m.get("struct"), "ops")
        self.assertEqual(m.get("field"), "run")
        self.assertEqual(conf, 1.0)

    def test_manual_src_hash_recorded(self):
        row = self.con.execute(
            "SELECT value FROM meta WHERE key='manual_src_hash'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(len(row[0]), 64)   # sha256 hex

    def test_manual_link_edge(self):
        self.assertIn(("dispatch_op", "extra_handler"), self.pairs("fnptr"))
        conf = self.con.execute(
            "SELECT confidence FROM edges WHERE origin='manual'").fetchone()[0]
        self.assertEqual(conf, 1.0)

    # ---- codex review 修正驗證 ----

    def test_static_header_fn_callable_from_includer(self):
        # codex 致命問題 3:static inline in .h
        self.assertIn(("use_cfg", "sub1/config.h::cfg_get"),
                      self.pairs("calls"))

    def test_include_dup_basename_not_cross_linked(self):
        # codex 高風險 4:重名 header 依 #include 內容比對
        inc = self.pairs("includes")
        self.assertIn(("caller.c", "sub1/config.h"), inc)
        self.assertNotIn(("caller.c", "sub2/config.h"), inc)

    def test_rmw_write_site_also_reads(self):
        # codex 高風險 5:counter++ 同站點補 reads(meta.rmw)
        self.assertIn(("bump", "counter"), self.pairs("writes"))
        self.assertIn(("bump", "counter"), self.pairs("reads"))
        metas = [m for (m,) in self.con.execute(
            "SELECT e.meta FROM edges e JOIN nodes n1 ON n1.id=e.src "
            "WHERE n1.name='bump' AND e.kind IN ('reads','writes')")]
        self.assertTrue(any("rmw" in m for m in metas), metas)

    def test_query_connection_readonly(self):
        ro = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            ro.execute("DELETE FROM edges")
        ro.close()

    # ---- L2' macro 維度 ----

    def test_macro_node_and_expands_edge(self):
        kind = self.con.execute(
            "SELECT kind FROM nodes WHERE name='MAX2'").fetchone()
        self.assertEqual(kind[0], "macro")
        self.assertIn(("add", "MAX2"), self.pairs("expands"))

    def test_signature_filled(self):
        sig = self.con.execute(
            "SELECT signature FROM nodes WHERE qname='add'").fetchone()[0]
        self.assertIn("int a", sig or "")

    # ---- views / meta ----

    def test_edge_pairs_view_aggregates(self):
        row = self.con.execute(
            "SELECT site_count, origins FROM edge_pairs p "
            "JOIN nodes n2 ON n2.id=p.dst "
            "WHERE n2.qname='add' AND p.kind='calls'").fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "cscope")

    def test_meta_provenance(self):
        engines = json.loads(self.con.execute(
            "SELECT value FROM meta WHERE key='engines_run'").fetchone()[0])
        self.assertEqual(engines[0]["layers"], "L0+L1+L3")


CLINK = os.environ.get("CCODEGRAPH_CLINK", "clink")


@unittest.skipUnless(tools_ok() and shutil.which(CLINK),
                     "needs clink binary (set CCODEGRAPH_CLINK)")
class TestClinkImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "miniproj")
        shutil.copytree(FIXTURE, cls.root)
        cls.db = os.path.join(cls.root, ig.DB_NAME)
        ig.build(cls.root, cls.db, jobs=4)
        ig.clink_import(cls.root, cls.db)
        cls.con = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.tmp)

    def test_clink_calls_edge_with_parse_time_parent(self):
        rows = set(self.con.execute(
            "SELECT n1.qname, n2.qname FROM edges e "
            "JOIN nodes n1 ON n1.id=e.src JOIN nodes n2 ON n2.id=e.dst "
            "WHERE e.origin='clink' AND e.kind='calls'"))
        self.assertIn(("main", "add"), rows)
        self.assertIn(("use_helper", "util.c::helper"), rows)

    def test_clink_writes_edge_catches_increment(self):
        # clink 語意層原生抓 counter++(cscope -L9 漏的)
        rows = set(self.con.execute(
            "SELECT n1.qname, n2.qname FROM edges e "
            "JOIN nodes n1 ON n1.id=e.src JOIN nodes n2 ON n2.id=e.dst "
            "WHERE e.origin='clink' AND e.kind='writes'"))
        self.assertIn(("bump", "counter"), rows)

    def test_rerunnable_no_duplicates(self):
        before = self.con.execute(
            "SELECT COUNT(*) FROM edges WHERE origin='clink'").fetchone()[0]
        ig.clink_import(self.root, self.db)
        con2 = sqlite3.connect(self.db)
        after = con2.execute(
            "SELECT COUNT(*) FROM edges WHERE origin='clink'").fetchone()[0]
        con2.close()
        self.assertEqual(before, after)

    def test_semantic_confirmed_on_real_edge(self):
        # L4/D3:cscope 邊被語意引擎確認 → meta.semantic=confirmed
        meta = self.con.execute(
            "SELECT e.meta FROM edges e JOIN nodes n1 ON n1.id=e.src "
            "JOIN nodes n2 ON n2.id=e.dst WHERE n1.name='main' "
            "AND n2.name='add' AND e.origin='cscope'").fetchone()[0]
        self.assertIn('"semantic":"confirmed"', meta.replace(" ", ""))

    def test_semantic_absent_on_inactive_ifdef(self):
        # gated.c:#ifdef FEATURE_X 未定義 → cscope 看得到、libclang 看不到
        meta = self.con.execute(
            "SELECT e.meta FROM edges e JOIN nodes n1 ON n1.id=e.src "
            "JOIN nodes n2 ON n2.id=e.dst WHERE n1.name='gated' "
            "AND n2.name='rarely' AND e.origin='cscope'").fetchone()[0]
        self.assertIn('"semantic":"absent"', meta.replace(" ", ""))
        # D3:confidence 不因 absent 降級
        conf = self.con.execute(
            "SELECT e.confidence FROM edges e JOIN nodes n1 ON n1.id=e.src "
            "WHERE n1.name='gated' AND e.origin='cscope'").fetchone()[0]
        self.assertEqual(conf, 0.90)

    def test_engines_run_appended(self):
        engines = json.loads(self.con.execute(
            "SELECT value FROM meta WHERE key='engines_run'").fetchone()[0])
        self.assertTrue(any(e.get("engine") == "clink" for e in engines))


if __name__ == "__main__":
    unittest.main()
