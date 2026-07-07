"""End-to-end tests — subprocess 跑 CLI 全流程(build → 各查詢動詞),
驗使用者實際看到的輸出文字。缺 cscope/ctags 時 skip(NFR4)。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CLI = os.path.join(REPO, "ccodegraph.py")
FIXTURE = os.path.join(REPO, "tests", "fixtures", "miniproj")


def tools_ok():
    if not (shutil.which("cscope") and shutil.which("ctags")):
        return False
    v = subprocess.run(["ctags", "--version"], capture_output=True, text=True)
    return "Universal Ctags" in v.stdout


@unittest.skipUnless(tools_ok(), "needs cscope + universal-ctags on PATH")
class TestCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "miniproj")
        shutil.copytree(FIXTURE, cls.root)
        out = cls.run_cli("build")
        assert "done:" in out, out

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    @classmethod
    def run_cli(cls, *args):
        r = subprocess.run([sys.executable, CLI, *args, "-p", cls.root],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    def test_schema_reports_fill_and_pending(self):
        out = self.run_cli("schema")
        self.assertIn("calls", out)
        self.assertIn("[cscope]", out)
        self.assertIn("[fnptr]", out)        # L3 已填
        self.assertIn("[callback]", out)
        self.assertIn("pending", out)
        self.assertIn("clangd", out)         # L4 未填要明講(P7)

    def test_callers_sectioned_for_dup_symbol(self):
        out = self.run_cli("callers", "app_init")
        self.assertIn("2 definitions", out)
        self.assertIn("alt_init.c::app_init", out)
        self.assertIn("alt_init2.c::app_init", out)
        self.assertIn("do_start", out)
        self.assertIn("ambiguous 2 candidates", out)   # D3 標籤到輸出層

    def test_callers_static_disambiguated(self):
        out = self.run_cli("callers", "helper")
        self.assertIn("2 definitions", out)
        # util.c 節只有 use_helper;main.c 節只有 main
        util_sec = out.split("## util.c::helper")[1].split("##")[0]
        self.assertIn("use_helper", util_sec)
        self.assertNotIn("- main", util_sec)

    def test_callers_by_qname_single_section(self):
        out = self.run_cli("callers", "util.c::helper")
        self.assertNotIn("definitions", out)   # 精確指定 → 不分節
        self.assertIn("use_helper", out)

    def test_callers_unknown_symbol_honest(self):
        out = self.run_cli("callers", "no_such_fn")
        self.assertIn("not found", out)

    def test_callees(self):
        out = self.run_cli("callees", "main")
        self.assertIn("add", out)
        self.assertIn("main.c::helper", out)

    def test_impact(self):
        out = self.run_cli("impact", "add", "-d", "2")
        self.assertIn("affects", out)                 # 仿 CodeGraph 標題
        self.assertIn("depth 1", out)
        self.assertIn("main", out)
        self.assertIn("by file:", out)                # 按檔分組
        self.assertIn("main.c: main:", out)

    def test_globals_writers_vs_readers(self):
        out = self.run_cli("globals", "counter")
        w = out.split("readers")[0]
        self.assertIn("main", w)
        self.assertIn("get_counter", out.split("readers")[1])

    def test_vars_of(self):
        out = self.run_cli("vars-of", "main")
        self.assertIn("counter", out)
        self.assertIn("[writes]", out)

    def test_who_includes(self):
        out = self.run_cli("who-includes", "util.h")
        self.assertIn("util.c", out)
        self.assertIn("main.c", out)

    def test_callback_tagged_in_callers(self):
        out = self.run_cli("callers", "cmp")
        self.assertIn("sort_things", out)
        self.assertIn("[callback]", out)

    def test_fnptr_and_manual_in_callers(self):
        out = self.run_cli("callers", "impl_run")
        self.assertIn("dispatch_op", out)
        self.assertIn("fnptr", out)
        out2 = self.run_cli("callers", "extra_handler")
        self.assertIn("dispatch_op", out2)
        self.assertIn("manual", out2)

    def test_impact_excludes_ambiguous_by_default(self):
        # D4:ambiguous 邊(app_init 雙定義)預設不進 impact
        out = self.run_cli("impact", "app_init", "-d", "1")
        self.assertNotIn("do_start", out)
        out2 = self.run_cli("impact", "app_init", "-d", "1", "--ambiguous")
        self.assertIn("do_start", out2)

    def test_manual_stale_warning(self):
        # 改 fnptr.json 後 schema 必須警告 manual 邊過期(FR3 stale)
        import os
        fp = os.path.join(self.root, "fnptr.json")
        with open(fp, "a") as fh:
            fh.write("\n")
        try:
            out = self.run_cli("schema")
            self.assertIn("STALE", out)
        finally:
            with open(fp) as fh:
                content = fh.read()
            with open(fp, "w") as fh:
                fh.write(content.rstrip() + "\n")

    def test_semantic_tag_shown_after_clink(self):
        import shutil as sh
        clink = os.environ.get("CCODEGRAPH_CLINK", "clink")
        if not sh.which(clink):
            self.skipTest("needs clink")
        r = subprocess.run([sys.executable, CLI, "clink-import", "-p",
                            self.root], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        out = self.run_cli("callers", "rarely")
        self.assertIn("semantic:confirmed", out)   # D14:token 層含 inactive 區

    def test_macro_callers(self):
        out = self.run_cli("callers", "MAX2")
        self.assertIn("add", out)

    def test_explore_one_shot(self):
        out = self.run_cli("explore", "main")
        self.assertIn("== main @ main.c:", out)
        self.assertIn("callers (", out)
        self.assertIn("callees (", out)
        self.assertIn("add", out)
        self.assertIn("main.c::helper", out)
        self.assertIn("counter  [writes]", out)

    def test_json_output_matches_text_fields(self):
        import json as j
        out = self.run_cli("callers", "add", "--json")
        res = j.loads(out)
        self.assertEqual(res["verb"], "callers")
        d = res["definitions"][0]
        self.assertEqual(d["qname"], "add")
        callers = {it["qname"] for it in d["items"]}
        self.assertIn("main", callers)
        it = next(x for x in d["items"] if x["qname"] == "main")
        self.assertIn("cscope", it["origins"])
        self.assertGreaterEqual(it["confidence"], 0.9)

    def test_json_schema_verb(self):
        import json as j
        res = j.loads(self.run_cli("schema", "--json"))
        self.assertIn("function", res["nodes"])
        self.assertTrue(any(e["kind"] == "calls" for e in res["edges"]))
        self.assertTrue(any(e2.get("layers") for e2 in res["engines_run"]))

    def test_json_explore(self):
        import json as j
        res = j.loads(self.run_cli("explore", "main", "--json"))
        d = res["definitions"][0]
        self.assertTrue(d["callees"])
        self.assertTrue(any(g["access"] == "writes" for g in d["globals"]))

    def test_products_confined_to_ccodegraph_dir(self):
        # FR6:產物全在 .ccodegraph/、自動 .gitignore、root 不得出現 cscope.out
        pdir = os.path.join(self.root, ".ccodegraph")
        self.assertTrue(os.path.exists(os.path.join(pdir, "graph.db")))
        self.assertTrue(os.path.exists(os.path.join(pdir, "cscope.out")))
        with open(os.path.join(pdir, ".gitignore")) as fh:
            self.assertEqual(fh.read().strip(), "*")
        self.assertFalse(os.path.exists(os.path.join(self.root, "cscope.out")))

    def test_skill_verb_prints_trust_calibration(self):
        # v4 skill 改版:RISK CHAPTER 壓縮為「Reading the labels」,內涵
        # (confidence 語意/semantic 旗標/ambiguous 處理)必須仍在。
        r = subprocess.run([sys.executable, CLI, "skill"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        self.assertIn("Reading the labels", r.stdout)
        self.assertIn("semantic:confirmed", r.stdout)
        self.assertIn("semantic:absent", r.stdout)
        self.assertIn("ambiguous N candidates", r.stdout)
        self.assertIn("user assertion", r.stdout)
        # D16:輸出上限的教學必須在 skill 裡(截斷行為要有文件依據)
        self.assertIn("--limit 0", r.stdout)

    def test_status_full_report(self):
        out = self.run_cli("status")
        self.assertIn("tools:", out)
        self.assertIn("ctags", out)
        self.assertIn("cscope", out)
        self.assertIn("products:", out)
        self.assertIn("graph.db", out)
        self.assertIn("artifact:", out)
        self.assertIn("aligned", out)          # 剛建完 → 對齊

    def test_status_health_and_issue_codes(self):
        out = self.run_cli("status")
        self.assertIn("health :", out)
        env = {**os.environ, "CCODEGRAPH_CTAG_PATH": "/oops"}   # 拼錯
        r = subprocess.run([sys.executable, CLI, "status", "-p", self.root],
                           capture_output=True, text=True, env=env)
        self.assertIn("ENV_UNKNOWN_VARS", r.stdout)
        self.assertIn("CCODEGRAPH_CTAG_PATH", r.stdout)

    def test_status_json_triage_fields(self):
        import json as j
        res = j.loads(self.run_cli("status", "--json"))
        self.assertEqual(res["status_schema_version"], 1)
        self.assertIn(res["health"], ("OK", "WARN", "ERROR"))
        self.assertIsInstance(res["issues"], list)
        self.assertTrue(res["tools"]["ctags"]["ok"])
        self.assertEqual(res["tools"]["ctags"]["flavor"], "universal")

    def test_status_detects_drift(self):
        p = os.path.join(self.root, "drift_probe.c")
        with open(p, "w") as fh:
            fh.write("int drift_probe(void) { return 0; }\n")
        try:
            out = self.run_cli("status")
            self.assertIn("added=1", out)
            self.assertIn("STALE_GRAPH", out)
            self.assertIn("build --incremental", out)
        finally:
            os.remove(p)

    def test_reset_removes_products_dir(self):
        import shutil as sh
        tmp2 = tempfile.mkdtemp()
        root2 = os.path.join(tmp2, "mp")
        sh.copytree(FIXTURE, root2)
        r = subprocess.run([sys.executable, CLI, "build", "-p", root2],
                           capture_output=True, text=True)
        assert r.returncode == 0
        r = subprocess.run([sys.executable, CLI, "reset", "-p", root2],
                           capture_output=True, text=True)
        self.assertIn("removed", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(root2, ".ccodegraph")))
        sh.rmtree(tmp2)

    def test_viz_3d_default(self):
        out = self.run_cli("viz")
        self.assertIn("wrote", out)
        p = os.path.join(self.root, ".ccodegraph", "graph-3d.html")
        with open(p) as fh:
            html = fh.read()
        self.assertIn("ForceGraph3D", html)
        self.assertIn("sort_things", html)
        self.assertIn('"module"', html)          # #1:module 屬性已入資料
        self.assertNotIn('"kind": "reads"', html)  # 預設不嵌 reads

    def test_viz_2d_focus_and_full(self):
        out = self.run_cli("viz", "--format", "html2d", "--focus", "cmp",
                           "-d", "1")
        self.assertIn("2 nodes", out)
        out2 = self.run_cli("viz", "--full", "--out",
                            os.path.join(self.root, ".ccodegraph", "f.html"))
        self.assertIn("reads", out2)             # kinds 清單含 reads

    def test_viz_without_graph_errors_helpfully(self):
        tmp2 = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, CLI, "viz", "-p", tmp2],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("build", r.stdout + r.stderr)
        shutil.rmtree(tmp2)

    def test_dumpdb_metadata(self):
        out = self.run_cli("dumpdb")
        self.assertIn("db      : graph.db", out)
        self.assertIn("history (append-only):", out)
        self.assertIn("build-full", out)
        self.assertIn("schema  : v2", out)

    def test_status_lists_databases(self):
        out = self.run_cli("status")
        self.assertIn("databases:", out)
        self.assertIn("graph.db", out)

    def test_sql_escape_hatch(self):
        out = self.run_cli("sql", "SELECT COUNT(*) FROM nodes")
        self.assertGreater(int(out.strip()), 5)


if __name__ == "__main__":
    unittest.main()
