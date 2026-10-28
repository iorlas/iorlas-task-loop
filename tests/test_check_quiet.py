"""A check that waits is not a hung check: only its wall limit stops it. Real processes, a real process table (CPU flat while one
sleeps), short limits. On 0.23.101 a silent sleeping check was stopped as hung after check_idle_min (this file failed there)."""
import json
import os
import contextlib
import io
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import test_engine as te  # noqa: E402
import tl  # noqa: E402
from taskloop.contracts import config  # noqa: E402
from test_engine import engine, pyc  # noqa: E402
from test_checks_speed import SpeedTest  # noqa: E402
from taskloop.adapters import activity  # noqa: E402

SLEEP_S = 5  # well past the 1.2 s the old watchdog allowed in this test


class Quiet(SpeedTest):
    def run_one(self, cmd, **check):
        eng = self.checks_engine(checks=[dict({"id": "q", "cmd": cmd, "group": "tests"}, **check)])  # pyrefly: ignore[bad-argument-type]
        return eng, eng.run_checks({"checks": [], "files": []}, "s")[0]

    def log(self, eng, kind):
        rows = [json.loads(line) for line in eng.log_path.read_text().splitlines()]
        return [r for r in rows if r["kind"] == kind]

    def test_a_silent_sleeping_check_past_the_old_idle_limit_is_not_stopped(self):
        eng, res = self.run_one(pyc("import time; time.sleep(%d)" % SLEEP_S))
        self.assertEqual((res.status, res.exit), ("passed", 0))
        self.assertEqual(self.log(eng, "kill"), [])

    def test_the_same_with_the_process_table_flat_by_construction(self):
        with mock.patch.object(activity, "tree_cpu", lambda pid: {pid: 0.0}):  # table available, CPU never grows
            eng, res = self.run_one(pyc("import time; time.sleep(%d)" % SLEEP_S))
        self.assertEqual((res.status, res.exit), ("passed", 0))

    def test_a_busy_silent_check_passes(self):
        eng, res = self.run_one(pyc("import time\nt=time.time()\nwhile time.time()-t < 3: sum(range(10000))"))
        self.assertEqual(res.status, "passed")

    def test_an_unknown_process_table_never_stops_a_check(self):
        with mock.patch.object(activity.procs, "table", lambda: None):
            eng, res = self.run_one(pyc("import time; time.sleep(%d)" % SLEEP_S))
        self.assertEqual(res.status, "passed")

    def test_the_wall_limit_stops_a_silent_check_and_its_whole_tree(self):
        mark = "73.%d" % os.getpid()
        cmd = pyc("import subprocess; subprocess.call(['sleep', %r])" % mark)
        t = time.time()
        eng, res = self.run_one(cmd, retry=2, wall_min=0.05)  # 3 s
        self.assertLess(time.time() - t, 30)
        self.assertEqual((res.status, res.exit), ("failed", 124))
        self.assertEqual([k["why"] for k in self.log(eng, "kill")], ["timeout"])
        time.sleep(0.5)
        self.assertEqual(subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True).stdout.strip(), "")

    def test_every_look_at_a_quiet_check_is_in_the_run_log(self):
        with mock.patch.object(activity, "ACTIVITY_EVERY", 1.0):
            eng, res = self.run_one(pyc("import time; time.sleep(%d)" % SLEEP_S))
        self.assertEqual(res.status, "passed")
        got = self.log(eng, "activity")
        self.assertGreaterEqual(len(got), 3)
        self.assertLessEqual(len(got), SLEEP_S + 1)
        s = got[-1]
        self.assertIn(s["cmd_id"], [c["id"] for c in self.log(eng, "cmd_start")])
        self.assertTrue(s["pids"] and s["cpu_s"] is not None and s["out_bytes"] == 0 and s["silent_s"] > 1)


class RetiredKeys(unittest.TestCase):
    """check_idle_min (engine) and idle_min (a check) cannot stop anything any more: a profile that still has them loads, says so
    once on one line each, and the file is not touched."""

    def test_a_profile_with_the_retired_keys_loads_warns_once_and_is_left_as_it_was(self):
        raw = json.dumps({"engine": {"check_idle_min": 3, "check_wall_min": 20,
                                     "checks": [{"id": "u", "argv": ["just", "u"], "idle_min": 2, "wall_min": 90}]}}, indent=1)
        tmp = te.tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f = Path(tmp.name) / ".task-loop.json"
        f.write_text(raw)
        before = f.read_bytes()
        err = io.StringIO()
        config._SAID.clear()
        with contextlib.redirect_stderr(err):
            for _ in range(2):
                profile = tl.load_profile(json.loads(f.read_text()))
        self.assertEqual((profile.engine.check_wall_min, profile.engine.checks[0].wall_min), (20, 90))
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2, lines)  # one per key, not per load
        self.assertTrue(all(".task-loop.json" in x and "retired and ignored; safe to delete" in x for x in lines))
        self.assertIn("engine.check_idle_min", lines[0])
        self.assertIn("engine.checks[0].idle_min", lines[1])
        self.assertEqual(f.read_bytes(), before)

    def test_an_unknown_key_still_fails(self):
        with self.assertRaises(SystemExit):
            tl.load_profile({"engine": {"check_idle_mins": 3}})


if __name__ == "__main__":
    unittest.main()
