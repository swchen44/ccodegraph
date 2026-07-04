"""Unit tests — 歸戶/消歧純函式(D1)與註記(D3),不碰 subprocess/sqlite。"""
import json
import unittest

import idealgraph as ig


def n(name, file, start=1, end=99, static=False, kind="function"):
    return {"name": name, "kind": kind, "file": file,
            "line_start": start, "line_end": end, "is_static": static}


class TestDetectStatic(unittest.TestCase):
    def test_same_line(self):
        self.assertTrue(ig.detect_static(["static int f(void) {"], 1))

    def test_kr_previous_line(self):
        # K&R 換行式:static int\nkr_fn(...)
        self.assertTrue(ig.detect_static(["static int", "kr_fn(int a)"], 2))

    def test_non_static(self):
        self.assertFalse(ig.detect_static(["int f(void) {"], 1))

    def test_static_in_word_not_token(self):
        # "staticky" 不是 static token
        self.assertFalse(ig.detect_static(["int staticky(void) {"], 1))


class TestAssignQnames(unittest.TestCase):
    def test_static_always_qualified(self):
        defs = ig.assign_qnames([n("helper", "a.c", static=True)])
        self.assertEqual(defs[0]["qname"], "a.c::helper")

    def test_unique_nonstatic_plain(self):
        defs = ig.assign_qnames([n("add", "util.c")])
        self.assertEqual(defs[0]["qname"], "add")

    def test_nonstatic_dup_all_qualified(self):
        # eloop.c / eloop_win.c 型:二選一連結的非 static 同名
        defs = ig.assign_qnames([n("app_init", "alt_init.c"),
                                 n("app_init", "alt_init2.c")])
        self.assertEqual({d["qname"] for d in defs},
                         {"alt_init.c::app_init", "alt_init2.c::app_init"})

    def test_same_file_ifdef_dup_gets_line_suffix(self):
        # wpa 實例:同一檔內 #ifdef 兩分支各定義一次同名函式
        defs = ig.assign_qnames([
            n("eloop_init", "eloop.c", start=100, static=False),
            n("eloop_init", "eloop.c", start=200, static=False)])
        self.assertEqual({d["qname"] for d in defs},
                         {"eloop.c::eloop_init", "eloop.c::eloop_init:200"})

    def test_same_name_different_kind_independent(self):
        defs = ig.assign_qnames([n("counter", "util.c"),
                                 n("counter", "util.c", kind="global")])
        self.assertEqual([d["qname"] for d in defs], ["counter", "counter"])


class TestAttributeSrc(unittest.TestCase):
    def setUp(self):
        # 兩個同名 main:站點行區間才能分
        self.index = {"main": [n("main", "main.c", 10, 20),
                               n("main", "main_win.c", 5, 15)]}

    def test_line_containment_exact(self):
        got = ig.attribute_src(self.index, "main", "main.c", 12)
        self.assertEqual(got["file"], "main.c")

    def test_same_file_unique_fallback(self):
        # 行區間外(ctags 缺 end),但同檔唯一 → 判定
        got = ig.attribute_src(self.index, "main", "main_win.c", 99)
        self.assertEqual(got["file"], "main_win.c")

    def test_unknown_name_none(self):
        self.assertIsNone(ig.attribute_src(self.index, "nope", "x.c", 1))

    def test_ambiguous_same_file_two_defs_none(self):
        # 同檔兩個同名定義且行區間都不包含 → 寧可漏報
        idx = {"f": [n("f", "a.c", 1, 5), n("f", "a.c", 10, 15)]}
        self.assertIsNone(ig.attribute_src(idx, "f", "a.c", 7))


class TestChooseDst(unittest.TestCase):
    def test_static_same_file_rule(self):
        cands = [n("helper", "util.c", static=True),
                 n("helper", "main.c", static=True)]
        viable = ig.choose_dst(cands, "util.c")
        self.assertEqual(len(viable), 1)
        self.assertEqual(viable[0]["file"], "util.c")

    def test_static_other_file_excluded(self):
        cands = [n("helper", "main.c", static=True)]
        self.assertEqual(ig.choose_dst(cands, "util.c"), [])

    def test_nonstatic_dup_all_viable(self):
        cands = [n("app_init", "alt_init.c"), n("app_init", "alt_init2.c")]
        self.assertEqual(len(ig.choose_dst(cands, "caller.c")), 2)

    def test_mixed_static_and_nonstatic(self):
        cands = [n("f", "a.c", static=True), n("f", "b.c")]
        viable = ig.choose_dst(cands, "c.c")   # a.c 的 static 不可及
        self.assertEqual([c["file"] for c in viable], ["b.c"])


class TestEdgeMeta(unittest.TestCase):
    def test_unambiguous_empty(self):
        self.assertEqual(ig.edge_meta(1), "{}")

    def test_ambiguous_annotated(self):
        m = json.loads(ig.edge_meta(2))
        self.assertEqual(m, {"ambiguous": True, "candidates": 2,
                             "rule": "non-static-dup"})

    def test_extra_preserved(self):
        m = json.loads(ig.edge_meta(1, {"clangd": "confirmed"}))
        self.assertEqual(m, {"clangd": "confirmed"})


class TestConfidenceTable(unittest.TestCase):
    def test_iron_rule_ordering(self):
        # manual 永遠最高;啟發式 callback 在預設門檻邊上;git 最低
        c = ig.CONFIDENCE
        self.assertEqual(c["manual"], 1.0)
        self.assertGreater(c["clangd"], c["cscope"])
        self.assertGreater(c["cscope"], c["treesitter"])
        self.assertGreaterEqual(c["callback"], 0.7)
        self.assertLess(c["git"], 0.7)


if __name__ == "__main__":
    unittest.main()
