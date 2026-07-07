"""D16 顯式截斷單元測試 — in-memory SQLite 合成圖(不需 ctags/cscope 等外部
工具,任何平台可跑)。驗證:預設截斷、--limit 0 全量、截斷尾行必印真實總數、
JSON 欄位、sql 逃生口行數上限。"""
import contextlib
import io
import sqlite3
import unittest

import ccodegraph as ig

N_CALLERS = 50  # 大於 DEFAULT_LIST_LIMIT(40),觸發截斷


def make_graph(n_callers: int = N_CALLERS) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(ig.SCHEMA_SQL)
    con.execute(
        "INSERT INTO nodes(id,name,qname,kind,file,line_start,line_end,"
        "signature,is_static,origin,confidence) VALUES "
        "(1,'hot_fn','a.c::hot_fn','function','a.c',10,20,'(void)',0,"
        "'ctags',0.95)")
    for i in range(n_callers):
        nid = 2 + i
        con.execute(
            "INSERT INTO nodes(id,name,qname,kind,file,line_start,line_end,"
            "signature,is_static,origin,confidence) VALUES "
            f"(?,?,?,'function','c{i}.c',1,5,'(void)',0,'ctags',0.95)",
            (nid, f"caller_{i:03d}", f"c{i}.c::caller_{i:03d}"))
        con.execute(
            "INSERT INTO edges(src,dst,kind,file,line,origin,confidence,meta)"
            f" VALUES (?,1,'calls','c{i}.c',3,'cscope',0.9,'{{}}')", (nid,))
    con.commit()
    return con


def capture(fn, *args) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue()


class TestTruncateItems(unittest.TestCase):
    def test_under_limit_untouched(self):
        items, total, trunc = ig.truncate_items([1, 2, 3], 40)
        self.assertEqual((items, total, trunc), ([1, 2, 3], 3, False))

    def test_over_limit_cut_with_true_total(self):
        items, total, trunc = ig.truncate_items(list(range(50)), 40)
        self.assertEqual(len(items), 40)
        self.assertEqual(total, 50)
        self.assertTrue(trunc)

    def test_limit_zero_means_unlimited(self):
        items, total, trunc = ig.truncate_items(list(range(50)), 0)
        self.assertEqual((len(items), total, trunc), (50, 50, False))


class TestSectionedLimit(unittest.TestCase):
    def setUp(self):
        self.con = make_graph()

    def tearDown(self):
        self.con.close()

    def test_default_limit_truncates_and_reports_total(self):
        res = ig.q_sectioned(self.con, "hot_fn", "dst", 0.7)
        d = res["definitions"][0]
        self.assertEqual(len(d["items"]), ig.DEFAULT_LIST_LIMIT)
        self.assertEqual(d["total"], N_CALLERS)          # JSON 也看得到真實總數
        self.assertTrue(d["truncated"])
        out = capture(ig.render_sectioned, res)
        self.assertIn(f"+{N_CALLERS - ig.DEFAULT_LIST_LIMIT} more "
                      f"(total {N_CALLERS}; use --limit 0 for all)", out)

    def test_limit_zero_full_output(self):
        res = ig.q_sectioned(self.con, "hot_fn", "dst", 0.7, limit=0)
        d = res["definitions"][0]
        self.assertEqual(len(d["items"]), N_CALLERS)
        self.assertFalse(d["truncated"])
        self.assertNotIn("more (total", capture(ig.render_sectioned, res))


class TestExploreLimit(unittest.TestCase):
    def setUp(self):
        self.con = make_graph()

    def tearDown(self):
        self.con.close()

    def test_header_shows_true_total_not_truncated_count(self):
        res = ig.q_explore(self.con, "hot_fn", 0.7)
        d = res["definitions"][0]
        self.assertEqual(len(d["callers"]), ig.DEFAULT_LIST_LIMIT)
        self.assertEqual(d["callers_total"], N_CALLERS)
        out = capture(ig.render_explore, res)
        # 節標題必須是真實總數——枚舉題的 COUNT 交叉核對靠這個
        self.assertIn(f"callers ({N_CALLERS}):", out)
        self.assertIn("use --limit 0 for all", out)

    def test_limit_zero_full(self):
        res = ig.q_explore(self.con, "hot_fn", 0.7, limit=0)
        self.assertEqual(len(res["definitions"][0]["callers"]), N_CALLERS)


class TestRunSqlCap(unittest.TestCase):
    def setUp(self):
        self.con = make_graph()

    def tearDown(self):
        self.con.close()

    def test_cap_stops_with_explicit_notice(self):
        out = capture(ig.run_sql, self.con,
                      "SELECT id FROM nodes ORDER BY id", 5)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 6)                  # 5 rows + 截斷尾行
        self.assertIn("truncated at 5 rows (more remain)", lines[-1])

    def test_cap_zero_unlimited_no_notice(self):
        out = capture(ig.run_sql, self.con,
                      "SELECT id FROM nodes ORDER BY id", 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), N_CALLERS + 1)      # 全部節點,無尾行
        self.assertNotIn("truncated", out)

    def test_result_exactly_at_cap_no_notice(self):
        out = capture(ig.run_sql, self.con,
                      "SELECT id FROM nodes ORDER BY id", N_CALLERS + 1)
        self.assertNotIn("truncated", out)               # 剛好等於上限不誤報


if __name__ == "__main__":
    unittest.main()
