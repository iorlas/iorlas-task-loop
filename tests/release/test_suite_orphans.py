"""No pytest worker outlives the launcher that started it: a wall limit, an interrupt and a dead launcher each end every process."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.waits import until

from taskloop.adapters import landlock
from taskloop.app.release import suite
from taskloop.app.release.shell import Abort

ROOT = Path(__file__).resolve().parents[2]


class OneSuitePerHost(unittest.TestCase):
    def test_a_second_suite_waits_for_the_first_and_says_who_holds_it(self):
        said, ran = [], threading.Event()
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "suite-host.lock"
            with mock.patch.object(suite, "suite_lock_path", return_value=lock), mock.patch.object(suite, "say", said.append), \
                    mock.patch.object(suite, "_host_suite", side_effect=lambda *a: ran.set()):
                with landlock.os_lock(lock, "pid 1 since 10:00:00: the first suite"):
                    t = threading.Thread(target=suite.host_suite, args=(ROOT, ROOT))
                    t.start()
                    self.assertTrue(until(lambda: any("held by pid 1 since 10:00:00: the first suite" in m for m in said), 15))
                    self.assertFalse(ran.is_set())
                t.join(30)
                self.assertTrue(ran.is_set())
        self.assertTrue(any("waiting for the suite lock" in m for m in said))


class MemoryLimits(unittest.TestCase):

    def test_a_host_with_less_free_memory_than_the_budgets_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemTotal: 99999999 kB\nMemAvailable:     3145728 kB\nMemFree: 1 kB\n")
            with mock.patch.object(suite, "MEMINFO", info), mock.patch.object(suite, "PROC_CGROUP", Path(d) / "no-cgroup"):
                self.assertEqual(suite.available_mb(), 3072)
                suite.refuse_if_short(1, suite.available_mb())  # 3072 MB covers one worker
                with self.assertRaises(Abort) as raised:
                    suite.refuse_if_short(3, suite.available_mb())
            line = str(raised.exception)
            self.assertEqual(len(line.splitlines()), 1)
            self.assertIn("3072 MB available", line)
            self.assertIn(f"{3 * suite.WORKER_BUDGET_MB} MB needed", line)

    def test_the_suite_refuses_before_running_when_memory_is_short(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemAvailable:     1024 kB\n")
            with mock.patch.object(suite, "MEMINFO", info), mock.patch.object(suite, "PROC_CGROUP", Path(d) / "no-cgroup"), \
                    mock.patch.object(suite, "suite_lock_path", return_value=Path(d) / "l.lock"), \
                    mock.patch.object(suite, "run_parts") as ran, mock.patch.dict(os.environ, {"TASK_LOOP_SUITE_WORKERS": "2"}), \
                    self.assertRaises(Abort):
                suite.host_suite(ROOT, ROOT)
            ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
