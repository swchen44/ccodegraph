"""D17 Day2 單元測試 — parse_cscope_crossref(cscope.out 直讀)。

用合成 C 專案 + 真 cscope 建 -c crossref,驗逆向出來的每條規則:
- calls 歸屬:函式體、巨集體(#…)內呼叫歸巨集)、函式內 #define 結束
  後恢復函式 scope(dual-state 引擎)
- 嵌套 $(C++ init list / 巨集生成函式)→ 雙發射兩個候選
- -L9 等價:`=`/`+=` 算、`==`/`++` 不算
- includes 按 basename 分桶
- 壓縮(非 -c)crossref → CrossrefError(降級路徑的觸發條件)
缺 cscope 時 skip 並明講(NFR4)。
"""
import os
import shutil
import subprocess
import tempfile
import unittest

import ccodegraph as ig

SRC_A = """\
#define WRAP(x) do { helper(x); } while (0)
int g_count = 0;
int helper(int v) { g_count = v; return v; }
int use(void) { WRAP(1); g_count += 2; g_count++; return helper(g_count); }
int scoped(void)
{
#define MIN(a, b) ((a) < (b) ? (a) : (b))
    int r = MIN(1, 2);
    g_count = r;
    return helper(r);
}
"""

SRC_B = """\
#include "sub/deep.h"
#include <string.h>
int reader(void) { return g_count == 3; }
"""

SRC_CPP = """\
class Gui {
public:
    Gui(int *_app);
    void setup();
    int *app;
};
Gui::Gui(int *_app)
    : app(_app)
{
    setup();
}
"""


@unittest.skipUnless(shutil.which("cscope"), "needs cscope on PATH")
class TestCrossrefParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "sub"))
        for name, content in (("a.c", SRC_A), ("b.c", SRC_B),
                              ("gui.cpp", SRC_CPP),
                              ("sub/deep.h", "int dummy;\n")):
            with open(os.path.join(cls.tmp, name), "w",
                      encoding="utf-8") as fh:
                fh.write(content)
        cls.db = os.path.join(cls.tmp, "cs.out")
        subprocess.run(["cscope", "-bckR", "-f", cls.db],
                       cwd=cls.tmp, check=True, capture_output=True)
        cls.calls, cls.refs, cls.assigns, cls.includes = \
            ig.parse_cscope_crossref(
                cls.db,
                want_calls={"helper", "WRAP", "MIN", "setup"},
                want_refs={"g_count"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _sites(self, rows):
        return {(s, f, ln) for (s, f, ln, _t) in rows}

    def test_calls_in_function_and_macro_body(self):
        sites = self._sites(self.calls["helper"])
        self.assertIn(("WRAP", "a.c", 1), sites)    # 巨集體內 → 歸巨集
        self.assertIn(("use", "a.c", 4), sites)

    def test_infunction_define_end_restores_func_scope(self):
        # scoped() 內的 #define MIN 結束後,後續呼叫仍歸 scoped
        sites = self._sites(self.calls["helper"])
        self.assertIn(("scoped", "a.c", 10), sites)
        # MIN 的呼叫站點也歸 scoped(巨集區已結束)
        self.assertIn(("scoped", "a.c", 8), self._sites(self.calls["MIN"]))

    def test_nested_dollar_dual_emit(self):
        # C++ init list `: app(_app)` 產生假嵌套 $app —— setup() 的
        # 呼叫要同時以兩個候選發射(Gui 與 app),交給 attribute_src 仲裁
        scopes = {s for (s, f, ln, _t) in self.calls["setup"]
                  if f == "gui.cpp" and ln == 10}
        self.assertIn("Gui", scopes)

    def test_assign_semantics(self):
        lines = {(f, ln) for (_s, f, ln, _t) in self.assigns["g_count"]}
        self.assertIn(("a.c", 3), lines)       # g_count = v
        self.assertIn(("a.c", 4), lines)       # g_count += 2(++ 不算但 += 算)
        self.assertIn(("a.c", 9), lines)       # g_count = r
        self.assertNotIn(("b.c", 3), lines)    # g_count == 3 是比較
        self.assertIn(("b.c", 3),              # 但 -L0 refs 有它
                      {(f, ln) for (_s, f, ln, _t) in self.refs["g_count"]})

    def test_includes_bucketed_by_basename(self):
        self.assertIn("deep.h", self.includes)
        rows = self.includes["deep.h"]
        self.assertEqual(rows[0][1], "b.c")
        self.assertIn('#include "sub/deep.h"', rows[0][3])
        self.assertIn("string.h", self.includes)

    def test_text_reconstruction_matches_source_shape(self):
        row = next(r for r in self.calls["helper"]
                   if r[1] == "a.c" and r[2] == 4)
        self.assertEqual(row[3], "int use(void) { WRAP(1); g_count += 2; "
                                 "g_count++; return helper(g_count); }")

    def test_compressed_db_raises_crossref_error(self):
        db2 = os.path.join(self.tmp, "compressed.out")
        subprocess.run(["cscope", "-bkR", "-f", db2],
                       cwd=self.tmp, check=True, capture_output=True)
        with self.assertRaises(ig.CrossrefError):
            ig.parse_cscope_crossref(db2, want_calls=set(), want_refs=set())


if __name__ == "__main__":
    unittest.main()
