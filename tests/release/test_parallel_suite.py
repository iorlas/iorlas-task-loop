"""The release gate's pytest runs: the merge of their outputs, the failure report, the worker count and the per-run HOME."""
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.adapters.suiteout import Part, failing_tests, failure_report, merge_outputs, ran_line
from taskloop.app.release import suite as runner
from taskloop.contracts.env import Env, snapshot

GREEN = "..........\n10 passed, 2 skipped in 1.50s\n"
RED = textwrap.dedent("""\
    ..F.E
    =================================== FAILURES ===================================
    ____________________________ X.test_b ____________________________
    Traceback
    AssertionError: boom
    =============================== warnings summary ===============================
    tests/test_x.py::X::test_a
      DeprecationWarning: noisy
    =========================== short test summary info ============================
    FAILED tests/test_x.py::X::test_b - AssertionError: boom
    ERROR tests/test_x.py::X::test_c - ValueError: bang
    ======================== 1 failed, 1 error, 3 passed in 0.50s ========================
    """)


class Merge(unittest.TestCase):
    def test_green_runs_are_green_and_each_keeps_its_name_and_exit(self):
        out, green = merge_outputs([Part("parallel", 0, GREEN), Part("serial", 0, GREEN)])
        self.assertTrue(green)
        self.assertIn("== parallel (exit 0) ==", out)
        self.assertIn("== serial (exit 0) ==", out)

    def test_one_red_run_is_red_and_the_failure_sections_stay(self):
        out, green = merge_outputs([Part("parallel", 1, RED), Part("serial", 0, GREEN)])
        self.assertFalse(green)
        self.assertIn("AssertionError: boom", out)

    def test_failure_report_keeps_the_failures_and_the_summary_not_the_warnings_nor_the_dots(self):
        rep = failure_report(RED)
        for want in ("FAILURES", "AssertionError: boom", "FAILED tests/test_x.py::X::test_b", "1 failed, 1 error, 3 passed"):
            self.assertIn(want, rep)
        self.assertNotIn("noisy", rep)
        self.assertNotIn("..F.E", rep)

    def test_failing_tests_are_the_node_ids_of_the_short_summary(self):
        self.assertEqual(failing_tests(RED), ["tests/test_x.py::X::test_b", "tests/test_x.py::X::test_c"])

    def test_the_closing_line_is_found_or_there_is_none(self):
        self.assertEqual(ran_line(RED), "1 failed, 1 error, 3 passed in 0.50s")
        self.assertEqual(ran_line("Segmentation fault\n"), "no summary")


class Workers(unittest.TestCase):
    def test_default_is_the_smaller_of_cpus_and_ram_over_the_per_shard_budget_never_below_one(self):
        gb = 1024
        cases = ((8, 30 * gb, 8), (8, 6 * gb, 3), (14, 64 * gb, 14), (8, 100, 1), (1, 30 * gb, 1), (4, None, 4), (None, 8 * gb, 1))
        for cpus, mem, want in cases:
            self.assertEqual(runner.host_workers(cpus or 1, mem), want, (cpus, mem))
        with mock.patch.object(runner, "available_mb", return_value=5 * gb), mock.patch.object(os, "cpu_count", return_value=8):
            self.assertEqual(runner.workers(Env()), 2)

    def test_available_ram_is_read_from_the_host(self):
        self.assertGreater(runner.available_mb() or 1, 0)

    def test_the_environment_overrides_it(self):
        self.assertEqual(runner.workers(Env({"TASK_LOOP_SUITE_WORKERS": "3"})), 3)

    def test_a_run_gets_its_own_home_config_and_temp_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = runner.isolated_env(Path(d) / "a", snapshot()), runner.isolated_env(Path(d) / "b", snapshot())
            for k in ("HOME", "XDG_CONFIG_HOME", "TMPDIR"):
                self.assertNotEqual(a[k], b[k])
                self.assertTrue(a[k].startswith(str(Path(d) / "a")))
                self.assertTrue(Path(a[k]).is_dir())


if __name__ == "__main__":
    unittest.main()
