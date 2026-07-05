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
        self.assertIn("depth 1", out)
        self.assertIn("main", out)

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

    def test_macro_callers(self):
        out = self.run_cli("callers", "MAX2")
        self.assertIn("add", out)

    def test_sql_escape_hatch(self):
        out = self.run_cli("sql", "SELECT COUNT(*) FROM nodes")
        self.assertGreater(int(out.strip()), 5)


if __name__ == "__main__":
    unittest.main()
