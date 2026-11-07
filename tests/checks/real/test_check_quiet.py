"""A check that waits is not a hung check: only its wall limit stops it. Real processes, a real process table (CPU flat while one
sleeps), short limits. On 0.23.101 a silent sleeping check was stopped as hung after check_idle_min (this file failed there)."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from checks.test_checks_speed import SpeedTest
from taskloop.adapters.clock import SystemClock


class Quiet(SpeedTest):
    def run_one(self, cmd, **check):
        eng = self.checks_engine(checks=[dict({"id": "q", "cmd": cmd, "group": "tests"}, **check)], clock=SystemClock())  # pyrefly: ignore[bad-argument-type]
        return eng, eng.run_checks({"checks": [], "files": []}, "s")[0]

    def log(self, eng, kind):
        return eng.records(kind)
    def test_a_wall_hit_check_leaves_one_start_and_end_with_wall_hit_and_a_quiet_one_does_not(self):
        eng, res = self.run_one("sleep 30", wall_min=0.01)
        assert (res.exit, res.wall_hit) == (124, True)
        start, end = self.log(eng, "check_start")[-1], self.log(eng, "check_end")[-1]
        assert (end["id"], end["exit"], end["wall_hit"]) == (start["id"], 124, True)
        assert end["t"] - start["t"] >= 0.5
        eng, res = self.run_one("true")
        assert not self.log(eng, "check_end")[-1]["wall_hit"]
    def test_the_stop_flag_ends_a_running_check_and_its_tree(self):
        mark = f"74.{os.getpid()}"
        sleeper = self.script("sleeper.sh", f"sleep {mark}\n:\n")  # the shell stays the parent of the sleep
        eng = self.checks_engine(checks=[{"id": "q", "cmd": sleeper, "group": "tests"}], clock=SystemClock())
        timer = threading.Timer(1.0, eng.halt.set)
        timer.start()
        self.addCleanup(timer.cancel)
        t = time.time()
        res = eng.run_checks({"checks": [], "files": []}, "s")[0]
        assert time.time() - t < 30
        assert (res.status, res.wall_hit) == ("failed", False)
        assert [k["why"] for k in self.log(eng, "kill")] == ["stopped"]
        time.sleep(0.5)
        assert subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True, check=False).stdout.strip() == ""
