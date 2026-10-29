"""A check that waits is not a hung check: only its wall limit stops it. Real processes, a real process table (CPU flat while one
sleeps), short limits. On 0.23.101 a silent sleeping check was stopped as hung after check_idle_min (this file failed there)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support.engine_case import pyc
from test_checks_speed import SpeedTest

from taskloop.app.wire import slots as wslots
from taskloop.contracts import config


class Quiet(SpeedTest):
    def run_one(self, cmd, **check):
        eng = self.checks_engine(checks=[dict({"id": "q", "cmd": cmd, "group": "tests"}, **check)])  # pyrefly: ignore[bad-argument-type]
        return eng, eng.run_checks({"checks": [], "files": []}, "s")[0]

    def log(self, eng, kind):
        rows = [json.loads(line) for line in eng.log_path.read_text().splitlines()]
        return [r for r in rows if r["kind"] == kind]

    def test_a_silent_sleeping_check_is_not_stopped(self):
        eng, res = self.run_one(pyc("import time; time.sleep(1)"))
        self.assertEqual((res.status, res.exit), ("passed", 0))
        self.assertEqual(self.log(eng, "kill"), [])

    def test_a_busy_silent_check_passes(self):
        _eng, res = self.run_one(pyc("import time\nt=time.time()\nwhile time.time()-t < 0.3: sum(range(10000))"))
        self.assertEqual(res.status, "passed")

    def test_a_wall_hit_check_leaves_one_start_and_end_with_wall_hit_and_a_quiet_one_does_not(self):
        eng, res = self.run_one(pyc("import time; time.sleep(30)"), wall_min=0.01)
        self.assertEqual((res.exit, res.wall_hit), (124, True))
        start, end = self.log(eng, "check_start")[-1], self.log(eng, "check_end")[-1]
        self.assertEqual((end["id"], end["exit"], end["wall_hit"]), (start["id"], 124, True))
        self.assertGreaterEqual(end["t"] - start["t"], 0.5)
        eng, res = self.run_one(pyc("pass"))
        self.assertFalse(self.log(eng, "check_end")[-1]["wall_hit"])

    def test_the_stop_flag_ends_a_running_check_and_its_tree(self):
        mark = f"74.{os.getpid()}"
        eng = self.checks_engine(checks=[{"id": "q", "cmd": pyc(f"import subprocess; subprocess.call(['sleep', {mark!r}])"),  # pyrefly: ignore[bad-argument-type]
                                          "group": "tests"}])
        timer = threading.Timer(1.0, eng.halt.set)
        timer.start()
        self.addCleanup(timer.cancel)
        t = time.time()
        res = eng.run_checks({"checks": [], "files": []}, "s")[0]
        self.assertLess(time.time() - t, 30)
        self.assertEqual((res.status, res.wall_hit), ("failed", False))
        self.assertEqual([k["why"] for k in self.log(eng, "kill")], ["stopped"])
        time.sleep(0.5)
        self.assertEqual(subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True, check=False).stdout.strip(), "")


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
                profile = wslots.load_profile(json.loads(f.read_text()))
        self.assertEqual((profile.engine.check_wall_min, profile.engine.checks[0].wall_min), (20, 90))
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2, lines)  # one per key, not per load
        self.assertTrue(all(".task-loop.json" in x and "retired and ignored; safe to delete" in x for x in lines))
        self.assertIn("engine.check_idle_min", lines[0])
        self.assertIn("engine.checks[0].idle_min", lines[1])
        self.assertEqual(f.read_bytes(), before)

    def test_each_renamed_key_fails_naming_the_new_one_and_a_retired_one_does_not(self):
        rows = [({"engine": {"checks": [{"id": "a", "argv": ["x"]}, {"id": "b", "argv": ["x"], "timeout_min": 5}]}},
                 "checks[1]: timeout_min was renamed to wall_min"),
                ({"engine": {"check_timeout_min": 30}}, "engine: check_timeout_min was renamed to check_wall_min")]
        for raw, msg in rows:
            with self.subTest(msg):
                with self.assertRaises(config.ConfigError) as cm:
                    config.load(raw)
                self.assertIn(msg, str(cm.exception))
        self.assertEqual(config.load({"engine": {"check_idle_min": 3}}).engine.check_wall_min, 60)

    def test_an_unknown_key_still_fails(self):
        with self.assertRaises(SystemExit):
            wslots.load_profile({"engine": {"check_idle_mins": 3}})


if __name__ == "__main__":
    unittest.main()
