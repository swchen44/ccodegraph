"""Unit tests — 歸戶/消歧純函式(D1)與註記(D3),不碰 subprocess/sqlite。"""
import json
import os
import typing
import unittest

import ccodegraph as ig


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

    def test_prev_statement_static_does_not_leak(self):
        # ops.c 誤判案例:上一行是完整 static 敘述(; 結尾)
        lines = ["static struct ops OPS = { .run = impl_run };",
                 "int dispatch_op(struct ops *o) { return o->run(); }"]
        self.assertFalse(ig.detect_static(lines, 2))

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
    def test_static_header_visible_to_includers(self):
        # codex 致命問題 3:static inline in .h 可被 includer 呼叫
        cands = [n("cfg_get", "sub1/config.h", static=True)]
        self.assertEqual(len(ig.choose_dst(cands, "caller.c")), 1)

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




class TestStripCLine(unittest.TestCase):
    def test_string_literal_removed(self):
        clean, blk = ig.strip_c_line('const char *s = "cmp(x)";', False)
        self.assertNotIn("cmp", clean)
        self.assertFalse(blk)

    def test_line_comment_removed(self):
        clean, _ = ig.strip_c_line("int x; // call cmp(x)", False)
        self.assertNotIn("cmp", clean)

    def test_block_comment_state_carries(self):
        _clean, blk = ig.strip_c_line("int a; /* start", False)
        self.assertTrue(blk)
        clean2, blk2 = ig.strip_c_line("cmp(x) */ int b;", blk)
        self.assertNotIn("cmp", clean2)
        self.assertIn("int b;", clean2)
        self.assertFalse(blk2)

    def test_escaped_quote_in_string(self):
        clean, _ = ig.strip_c_line(r'p = "a\"cmp(x)"; q(r);', False)
        self.assertNotIn("cmp", clean)
        self.assertIn("q(r)", clean)


class TestCallbackHits(unittest.TestCase):
    NAMES: typing.ClassVar[set[str]] = {"cmp", "handler", "my_sort"}

    def test_fn_as_argument(self):
        self.assertEqual(ig.callback_hits("my_sort(arr, cmp);", self.NAMES),
                         ["cmp"])

    def test_address_of(self):
        self.assertEqual(ig.callback_hits("reg(&handler);", self.NAMES),
                         ["handler"])

    def test_assignment_not_callback(self):
        # .field = fn 是 fnptr 註冊,不是 callback(prev 是 =)
        self.assertEqual(ig.callback_hits(".run = cmp;", self.NAMES), [])

    def test_direct_call_not_callback(self):
        self.assertEqual(ig.callback_hits("cmp(a, b);", self.NAMES), [])


class TestIsRmw(unittest.TestCase):
    def test_increment(self):
        self.assertTrue(ig.is_rmw("counter++;", "counter"))

    def test_compound_assign(self):
        self.assertTrue(ig.is_rmw("counter += 2;", "counter"))

    def test_self_reference(self):
        self.assertTrue(ig.is_rmw("counter = counter + 1;", "counter"))

    def test_plain_write(self):
        self.assertFalse(ig.is_rmw("counter = add(1, 2);", "counter"))


class TestIncludeMatches(unittest.TestCase):
    def test_basename(self):
        self.assertTrue(ig.include_matches("config.h", "sub1/config.h"))

    def test_dir_suffix_exact(self):
        self.assertTrue(ig.include_matches("sub1/config.h", "sub1/config.h"))

    def test_dir_suffix_mismatch(self):
        self.assertFalse(ig.include_matches("sub1/config.h", "sub2/config.h"))

    def test_deep_suffix(self):
        self.assertTrue(ig.include_matches("a/b.h", "src/x/a/b.h"))


class TestLoadManual(unittest.TestCase):
    def _write(self, tmp, content):
        import os
        p = os.path.join(tmp, "fnptr.json")
        with open(p, "w") as fh:
            fh.write(content)
        return tmp

    def test_missing_file_empty(self):
        import tempfile
        links, regs, digest = ig.load_manual(tempfile.mkdtemp())
        self.assertEqual((links, regs, digest), ([], [], None))

    def test_valid_both_sections(self):
        import tempfile
        d = self._write(tempfile.mkdtemp(),
                        '{"registrations": [{"struct": "ops", "field": "run",'
                        ' "handler": "h"}], "links": [{"src": "a", "dst": "b"}]}')
        links, regs, digest = ig.load_manual(d)
        self.assertEqual(len(links), 1)
        self.assertEqual(regs[0]["field"], "run")
        self.assertEqual(len(digest), 64)

    def test_registration_missing_handler_dies(self):
        import tempfile
        d = self._write(tempfile.mkdtemp(), '{"registrations": [{"field": "run"}]}')
        with self.assertRaises(SystemExit):
            ig.load_manual(d)

    def test_invalid_json_dies(self):
        import tempfile
        d = self._write(tempfile.mkdtemp(), '{oops')
        with self.assertRaises(SystemExit):
            ig.load_manual(d)


class TestClassifyCtags(unittest.TestCase):
    def test_universal(self):
        self.assertEqual(ig.classify_ctags(
            "Universal Ctags 6.1.0, Copyright (C) 2015-2023"), "universal")

    def test_exuberant(self):
        self.assertEqual(ig.classify_ctags(
            "Exuberant Ctags 5.8, Copyright (C) 1996-2009 Darren Hiebert"),
            "exuberant")

    def test_bsd_usage_output(self):
        # BSD ctags 不認 --version,吐 usage
        self.assertEqual(ig.classify_ctags(
            "usage: ctags [-BFadtuwvx] [-f tagsfile] file ..."), "bsd")

    def test_empty_output_treated_bsd(self):
        self.assertEqual(ig.classify_ctags(""), "bsd")


class TestMergeCompileDbs(unittest.TestCase):
    def _db(self, tmp, name, entries):
        import json as j
        import os
        p = os.path.join(tmp, name)
        with open(p, "w") as fh:
            j.dump(entries, fh)
        return p

    def test_file_level_union_and_first_wins(self):
        import tempfile
        t = tempfile.mkdtemp()
        a = self._db(t, "a.json", [
            {"directory": "/x", "file": "shared.c", "arguments": ["cc", "-DA"]},
            {"directory": "/x", "file": "only_a.c", "arguments": ["cc"]}])
        b = self._db(t, "b.json", [
            {"directory": "/x", "file": "shared.c", "arguments": ["cc", "-DB"]},
            {"directory": "/x", "file": "only_b.c", "arguments": ["cc"]}])
        entries, conflicts = ig.merge_compile_dbs([a, b])
        files = {e["file"] for e in entries}
        self.assertEqual(files, {"shared.c", "only_a.c", "only_b.c"})  # 聯集
        shared = next(e for e in entries if e["file"] == "shared.c")
        self.assertIn("-DA", shared["arguments"])   # first wins
        self.assertEqual(len(conflicts), 1)          # 規則不同 → 衝突回報

    def test_identical_rules_not_conflict(self):
        import tempfile
        t = tempfile.mkdtemp()
        e = {"directory": "/x", "file": "s.c", "arguments": ["cc"]}
        a = self._db(t, "a.json", [e])
        b = self._db(t, "b.json", [e])
        _, conflicts = ig.merge_compile_dbs([a, b])
        self.assertEqual(conflicts, [])

    def test_bad_json_dies(self):
        import os
        import tempfile
        t = tempfile.mkdtemp()
        p = os.path.join(t, "bad.json")
        with open(p, "w") as fh:
            fh.write("{not-an-array")
        with self.assertRaises(SystemExit):
            ig.merge_compile_dbs([p])


class TestSynthesizeCompileDb(unittest.TestCase):
    # 路徑用 tempdir + os.path.join 組期望值——Windows 反斜線相容(CI 首跑教訓)
    def setUp(self):
        import tempfile
        self.root = os.path.realpath(tempfile.mkdtemp())

    def _f(self, rel):
        return os.path.join(self.root, rel)

    def test_cpp_gets_cxx_flags(self):
        # W3:C++ 檔不能被當 C 餵(-xc 會讓 C++ 解析失敗退回模糊)
        entries = ig.synthesize_compile_db(self.root, ["a.c", "b.cpp", "c.cc"])
        by = {e["file"]: e["arguments"] for e in entries}
        self.assertIn("-xc", by[self._f("a.c")])
        self.assertIn("-xc++", by[self._f("b.cpp")])
        self.assertIn("-std=gnu++17", by[self._f("c.cc")])

    def test_entry_per_c_with_include_dirs(self):
        entries = ig.synthesize_compile_db(
            self.root, ["src/a.c", "src/inc/x.h", "lib/y.h", "lib/b.c", "top.h"])
        files = {e["file"] for e in entries}
        self.assertEqual(files, {self._f("src/a.c"), self._f("lib/b.c")})
        args = entries[0]["arguments"]
        self.assertIn("-Isrc/inc", args)
        self.assertIn("-Ilib", args)


class TestComputeChanges(unittest.TestCase):
    def test_partition(self):
        old = {"a.c": "h1", "b.c": "h2", "gone.c": "h3"}
        new = {"a.c": "h1", "b.c": "CHANGED", "new.c": "h4"}
        changed, added, deleted = ig.compute_changes(old, new)
        self.assertEqual(changed, {"b.c"})
        self.assertEqual(added, {"new.c"})
        self.assertEqual(deleted, {"gone.c"})


class TestCoChangePairs(unittest.TestCase):
    def test_count_and_min(self):
        groups = [["a.c", "b.c"], ["a.c", "b.c"], ["a.c", "c.c"]]
        pairs = ig.co_change_groups_to_pairs(groups, min_count=2)
        self.assertEqual(pairs, [("a.c", "b.c", 2)])

    def test_mega_commit_skipped(self):
        groups = [[f"f{i}.c" for i in range(30)]] * 5
        self.assertEqual(ig.co_change_groups_to_pairs(groups, cap=20), [])


class TestToolPath(unittest.TestCase):
    def test_env_override(self):
        import os
        os.environ["CCODEGRAPH_CSCOPE_PATH"] = "/opt/x/cscope"
        try:
            self.assertEqual(ig.tool_path("cscope"), "/opt/x/cscope")
        finally:
            del os.environ["CCODEGRAPH_CSCOPE_PATH"]

    def test_default_system_path(self):
        self.assertEqual(ig.tool_path("ctags"), "ctags")


class TestCscopeLinesLenient(unittest.TestCase):
    """D15:cscope 對單一符號的內部錯誤(實測:redis vendored jemalloc 的巨集
    CTL 被密集使用時觸發 'Internal error: cannot get source line from
    database',單執行緒 100% 重現,非併發競態)不得讓整個 build 中止——
    跳過該符號、計入 CSCOPE_SKIPPED,其餘符號正常處理。"""

    def setUp(self):
        ig.CSCOPE_SKIPPED.clear()

    def test_nonzero_rc_returns_empty_and_records_skip(self):
        import subprocess as sp
        import unittest.mock as mock
        fake = sp.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="Internal error: cannot get source line from database")
        with mock.patch("subprocess.run", return_value=fake):
            rows = ig.cscope_lines("/tmp", "3", "CTL")
        self.assertEqual(rows, [])
        self.assertEqual(len(ig.CSCOPE_SKIPPED), 1)
        self.assertEqual(ig.CSCOPE_SKIPPED[0][0], "CTL")

    def test_success_case_unaffected(self):
        import subprocess as sp
        import unittest.mock as mock
        fake = sp.CompletedProcess(
            args=[], returncode=0,
            stdout="a.c foo 10 foo();\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            rows = ig.cscope_lines("/tmp", "3", "foo")
        self.assertEqual(rows, [("foo", "a.c", 10, "foo();")])
        self.assertEqual(ig.CSCOPE_SKIPPED, [])


class TestModuleMap(unittest.TestCase):
    def _map(self, content):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "module_mapping.csv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def test_case_insensitive_and_chinese_module(self):
        rules = ig.load_module_map(self._map(
            "# comment\n^SRC/UTILS/,工具層\n^src/drivers/,驅動\n"))
        self.assertEqual(ig.module_of(rules, "src/utils/eloop.c"), "工具層")
        self.assertEqual(ig.module_of(rules, "SRC/DRIVERS/x.c"), "驅動")

    def test_first_match_wins_and_no_match_empty(self):
        rules = ig.load_module_map(self._map("utils,A\nutils,B\n"))
        self.assertEqual(ig.module_of(rules, "src/utils/a.c"), "A")
        self.assertEqual(ig.module_of(rules, "main.c"), "")

    def test_bad_regex_dies(self):
        with self.assertRaises(SystemExit):
            ig.load_module_map(self._map("([bad,X\n"))

    def test_missing_module_column_dies(self):
        with self.assertRaises(SystemExit):
            ig.load_module_map(self._map("okregex\n"))


class TestEmbeddedSkill(unittest.TestCase):
    def test_embedded_matches_file(self):
        # SKILL 內嵌於 ccodegraph.py(單檔可輸出);與 skills/ 檔案必須一致。
        # 改了 SKILL.md 卻沒跑 tools/embed_skill.py → 這裡紅。
        p = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
            "skills", "ccodegraph", "SKILL.md")
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(ig.SKILL_MD, fh.read())


if __name__ == "__main__":
    unittest.main()
