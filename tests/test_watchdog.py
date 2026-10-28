"""The activity look at a running check, on fake CPU, file and clock samples: no process, no load, no sleep. `cs.activity` says whether
a check did anything since the last look (CPU of its tree, files under the worktree); `cs.Sampler` logs it, throttled. Nothing here
stops a check: only its wall limit does. One real process checks the CPU sampler itself (slow tier)."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
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

    def test_an_unreadable_process_table_is_unknown_not_idle(self):
        seen = {"files": None, "cpu": {}}
        with mock.patch.object(cs.procs, "table", lambda: None), mock.patch.object(cs, "files_signature", lambda wt: FILES):
            self.assertIsNone(cs.tree_cpu(1))
            self.assertTrue(cs.activity("wt", 1, seen))
            self.assertTrue(cs.activity("wt", 1, seen))  # nothing moved, and still not called hung

    def test_a_real_table_with_no_tree_stays_idle(self):
        seen = {"files": None, "cpu": {}}
        with mock.patch.object(cs.procs, "table", lambda: {}), mock.patch.object(cs, "files_signature", lambda wt: FILES):
            self.assertEqual(cs.tree_cpu(1), {})
            cs.activity("wt", 1, seen)
            self.assertFalse(cs.activity("wt", 1, seen))

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
class Samples(unittest.TestCase):
    """The look at a running check: at most one ActivitySample per 30 s of its clock, whatever the check does. It judges nothing."""

    def sampler(self, cpu, now):
        clock = lambda: now[0]  # noqa: E731
        s = cs.Sampler("wt", 1, "m7", started=100.0, clock=clock)
        patches = (mock.patch.object(cs, "tree_cpu", lambda pid: None if cpu() is None else dict(cpu())),
                   mock.patch.object(cs, "files_signature", lambda wt: FILES))
        for pt in patches:
            pt.start()
            self.addCleanup(pt.stop)
        return s

    def test_one_sample_per_30_seconds_and_it_carries_cpu_files_and_output(self):
        now = [100.0]
        s = self.sampler(lambda: {1: 1.0, 2: 0.5}, now)
        first = s.take(out_bytes=10, last_output_t=100.0)
        assert first is not None
        self.assertEqual((first.cmd_id, first.secs, first.out_bytes, first.pids, first.cpu_s, first.files, first.file_bytes,
                          first.newest_mtime_ns), ("m7", 0.0, 10, [1, 2], 1.5, 3, 120, 1_000))
        for t in (101.0, 110.0, 129.9):
            now[0] = t
            self.assertIsNone(s.take(10, 100.0), t)
        now[0] = 130.0
        later = s.take(10, 100.0)
        assert later is not None
        self.assertEqual((later.secs, later.silent_s), (30.0, 30.0))  # flat CPU, flat files, no output: 30 s since anything moved

    def test_a_flat_tree_is_sampled_not_stopped_over_and_over(self):
        now = [100.0]
        s = self.sampler(lambda: {1: 0.0}, now)
        got = []
        for t in range(100, 100 + 600, 5):  # ten minutes of a sleeping check
            now[0] = float(t)
            x = s.take(0, 100.0)
            if x:
                got.append(x)
        self.assertEqual(len(got), 20)
        self.assertEqual(got[-1].silent_s, 570.0)

    def test_an_unknown_table_is_logged_as_unknown_cpu(self):
        now = [100.0]
        s = self.sampler(lambda: None, now)
        x = s.take(0, 100.0)
        assert x is not None
        self.assertEqual((x.cpu_s, x.pids), (None, []))


@tags.slow
class RealCpu(unittest.TestCase):
    def test_the_cpu_sampler_sees_a_real_process_spend_cpu(self):
        p = subprocess.Popen([sys.executable, "-c", "while True: sum(range(10000))"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        first = cs.tree_cpu(p.pid) or {}
        self.assertIn(p.pid, first)
        grew = waits.until(lambda: (cs.tree_cpu(p.pid) or {}).get(p.pid, 0) > first[p.pid], limit=60, poll=0.1)  # a loaded box only makes this slower
        self.assertTrue(grew)


if __name__ == "__main__":
    unittest.main()
