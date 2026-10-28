"""The hang watchdog's decisions, on fake CPU, file and clock samples: no process, no load, no sleep. `cs.activity` says whether a
check did anything since the last look (CPU of its tree, files under the worktree); `Engine._freeze_check` says, at a given
`now`, whether the silence has outlasted the idle limit. One real process checks the CPU sampler itself (slow tier)."""
import subprocess
import sys
import types
import unittest
from pathlib import Path
from threading import Lock
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from test_engine import engine  # noqa: E402
from taskloop.adapters import activity as cs  # noqa: E402
from support import tags, waits  # noqa: E402

FILES = (3, 120, 1_000)  # (files, bytes, newest mtime)


class Look:
    """The watchdog's successive looks at a check, with the CPU of its tree and the worktree's signature set per look."""

    def __init__(self, cpu, files=FILES):
        self.cpu, self.files, self.seen = cpu, files, {"files": None, "cpu": {}}
        self.look()  # the first look only takes the baseline

    def look(self, cpu=None, files=None):
        self.cpu = self.cpu if cpu is None else cpu
        self.files = self.files if files is None else files
        with mock.patch.object(cs, "tree_cpu", lambda pid: dict(self.cpu)), mock.patch.object(cs, "files_signature", lambda wt: self.files):
            return cs.activity("wt", 1, self.seen)


@tags.domain
class Activity(unittest.TestCase):
    def test_the_first_look_counts_as_activity(self):
        seen = {"files": None, "cpu": {}}
        with mock.patch.object(cs, "tree_cpu", lambda pid: {1: 0.0}), mock.patch.object(cs, "files_signature", lambda wt: FILES):
            self.assertTrue(cs.activity("wt", 1, seen))
            self.assertFalse(cs.activity("wt", 1, seen))

    def test_silent_and_idle_is_no_activity(self):
        w = Look({1: 2.0, 2: 5.0})
        self.assertFalse(w.look())
        self.assertFalse(w.look({1: 2.0, 2: 5.0}))

    def test_a_check_burning_cpu_with_no_output_or_files_is_active(self):
        w = Look({1: 2.0, 2: 5.0})
        self.assertTrue(w.look({1: 2.0, 2: 5.01}))  # one child spent a little CPU; nothing else moved
        self.assertTrue(w.look({1: 3.0, 2: 5.01}))
        self.assertFalse(w.look({1: 3.0, 2: 5.01}))

    def test_a_new_process_is_activity_and_a_finished_one_is_not(self):
        w = Look({1: 2.0, 2: 5.0})
        self.assertTrue(w.look({1: 2.0, 2: 5.0, 3: 0.0}))
        self.assertFalse(w.look({1: 2.0, 3: 0.0}))  # 2 exited: its CPU going away is not CPU spent

    def test_a_file_written_under_the_worktree_is_activity_whichever_part_of_its_signature_moved(self):
        w = Look({1: 2.0})
        for files in ((4, 120, 1_000), (4, 150, 1_000), (4, 150, 2_000)):
            self.assertTrue(w.look(files=files), files)
        self.assertTrue(w.look(files=(4, 150, 3_000)))  # touched only: the mtime moved
        self.assertFalse(w.look(files=(4, 150, 3_000)))


@tags.domain
class Verdict(unittest.TestCase):
    """Engine._freeze_check(why, idle, now): hung only when `now` is more than `idle` past the last observed activity."""

    def check(self, last=100.0):
        return types.SimpleNamespace(_event_lock=Lock(), _event_frozen=False, last_event_t=last, kill_t=0.0, killed=False, kill_why="")

    def verdict(self, c, now, idle=60.0):
        return engine.Engine._freeze_check(c, "hung", idle=idle, now=now)

    def test_silence_up_to_the_limit_is_not_hung_and_past_it_is(self):
        c = self.check()
        self.assertFalse(self.verdict(c, now=100.0))
        self.assertFalse(self.verdict(c, now=159.9))
        self.assertFalse(self.verdict(c, now=160.0))  # exactly the limit still waits
        self.assertTrue(self.verdict(c, now=160.1))
        self.assertEqual((c.killed, c.kill_why, c._event_frozen), (True, "hung", True))

    def test_output_or_a_file_write_resets_the_clock(self):
        c = self.check()
        self.assertFalse(self.verdict(c, now=150.0))
        c.last_event_t = 150.0  # what watch_output's mark() does for a chunk of output or a positive activity()
        self.assertFalse(self.verdict(c, now=209.0))
        self.assertTrue(self.verdict(c, now=210.5))

    def test_a_check_burning_cpu_keeps_the_clock_moving_a_silent_idle_one_does_not(self):
        busy, idle = self.check(), self.check()
        busy_look, idle_look = Look({1: 0.0}), Look({1: 0.0})
        for tick in range(1, 20):  # one look every 10 s of fake time; only the busy check spends CPU
            now = 100.0 + tick * 10
            if busy_look.look({1: float(tick)}):
                busy.last_event_t = now
            if idle_look.look():
                idle.last_event_t = now
            self.assertFalse(self.verdict(busy, now), tick)
        self.assertTrue(self.verdict(idle, 100.0 + 19 * 10))

    def test_it_decides_once_and_a_stopped_check_stays_stopped(self):
        c = self.check()
        self.assertTrue(self.verdict(c, now=500.0))
        self.assertFalse(self.verdict(c, now=900.0))
        self.assertLessEqual(c.last_event_t, c.kill_t)  # the boundary is frozen before the stop


@tags.slow
class Sampler(unittest.TestCase):
    def test_the_cpu_sampler_sees_a_real_process_spend_cpu(self):
        p = subprocess.Popen([sys.executable, "-c", "while True: sum(range(10000))"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        first = cs.tree_cpu(p.pid)
        self.assertIn(p.pid, first)
        grew = waits.until(lambda: cs.tree_cpu(p.pid).get(p.pid, 0) > first[p.pid], limit=60, poll=0.1)  # a loaded box only makes this slower
        self.assertTrue(grew)


if __name__ == "__main__":
    unittest.main()
