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

import idealgraph as ig

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
        f, l, conf = self.con.execute(
            "SELECT e.file, e.line, e.confidence FROM edges e "
            "JOIN nodes n2 ON n2.id=e.dst WHERE n2.qname='add' "
            "AND e.kind='calls'").fetchone()
        self.assertEqual(f, "main.c")
        self.assertGreater(l, 0)
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
        self.assertEqual(engines[0]["layer"], "L0+L1")


if __name__ == "__main__":
    unittest.main()
