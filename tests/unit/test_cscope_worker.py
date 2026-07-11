"""D17 單元測試 — cscope line-mode 常駐行程池的協定與失效語意。

真跑 cscope(miniproj fixture 建一個小索引),驗:
- 標頭解析 + `>> ` 提示符黏連(連續查詢)
- 「查無結果」回覆 `Unable to search database` → 空結果、不記 skip
- worker 亡故 → cscope_lines 重生重試,無辜符號不受牽連
- 連續兩次失敗 → 記入 CSCOPE_SKIPPED、回空(D15 語意)
缺 cscope 時 skip 並明講(NFR4)。
"""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import ccodegraph as ig

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "miniproj")


@unittest.skipUnless(shutil.which("cscope"), "needs cscope on PATH")
class TestCscopeWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "miniproj")
        shutil.copytree(FIXTURE, cls.root)
        os.makedirs(os.path.join(cls.root, ig.PRODUCTS_DIR), exist_ok=True)
        subprocess.run(
            ["cscope", "-bkRu", "-f", ig.CSCOPE_DB],
            cwd=cls.root, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        ig._close_cscope_workers()
        shutil.rmtree(cls.tmp)

    def setUp(self):
        ig.CSCOPE_SKIPPED.clear()

    def tearDown(self):
        ig._close_cscope_workers()
        ig._CSCOPE_TL.worker = None

    def test_query_hit_same_shape_as_dash_l(self):
        rows = ig.cscope_lines(self.root, "3", "app_init")
        self.assertIn(("do_start", "caller.c", 3), [r[:3] for r in rows])
        self.assertEqual(ig.CSCOPE_SKIPPED, [])

    def test_consecutive_queries_survive_prompt_glue(self):
        # 提示符 `>> ` 黏在第二個回覆的標頭前 — 連續查詢都要能解析
        first = ig.cscope_lines(self.root, "3", "app_init")
        second = ig.cscope_lines(self.root, "0", "counter")
        self.assertTrue(first and second)
        self.assertEqual(ig.CSCOPE_SKIPPED, [])

    def test_no_result_maps_to_empty_not_skip(self):
        rows = ig.cscope_lines(self.root, "3", "zzz_no_such_symbol")
        self.assertEqual(rows, [])
        self.assertEqual(ig.CSCOPE_SKIPPED, [])  # 查無結果 ≠ 失敗

    def test_worker_death_respawns_and_answers(self):
        w = ig._cscope_worker(self.root)
        w.proc.kill()
        w.proc.wait()
        rows = ig.cscope_lines(self.root, "3", "app_init")
        self.assertIn(("do_start", "caller.c", 3), [r[:3] for r in rows])
        self.assertEqual(ig.CSCOPE_SKIPPED, [])

    def test_double_failure_records_skip(self):
        # 毒符號情境:重試後仍失敗 → 記 skip、回空、不拋例外(D15)
        class DeadWorker:
            root = self.root
            def query(self, qflag, sym):
                return [], "simulated poison"
            def close(self):
                pass
        with mock.patch.object(ig, "_cscope_worker",
                               return_value=DeadWorker()):
            rows = ig.cscope_lines(self.root, "3", "poison_sym")
        self.assertEqual(rows, [])
        self.assertEqual(len(ig.CSCOPE_SKIPPED), 1)
        self.assertEqual(ig.CSCOPE_SKIPPED[0][0], "poison_sym")
        self.assertIn("simulated poison", ig.CSCOPE_SKIPPED[0][1])

    def test_pool_closes_workers_on_exit(self):
        with ig._CscopePool():
            w = ig._cscope_worker(self.root)
            self.assertIsNone(w.proc.poll())
        self.assertIsNotNone(w.proc.poll())
        self.assertEqual(ig._CSCOPE_WORKERS, [])

    def test_one_worker_per_thread(self):
        seen = {}

        def probe(tag):
            seen[tag] = id(ig._cscope_worker(self.root))

        t1 = threading.Thread(target=probe, args=("a",))
        t2 = threading.Thread(target=probe, args=("b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertNotEqual(seen["a"], seen["b"])
        self.assertEqual(len(ig._CSCOPE_WORKERS), 2)


if __name__ == "__main__":
    unittest.main()
