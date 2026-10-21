"""A hand run and a loop never share a slot (tl-bxk.9.5): run-task --slot takes the slot bead, a live engine in a slot's
worktree keeps it busy whatever its bead says, a hold reserves a slot for a person, and a stopped engine's worker dies
with it."""

import io
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_loop import LoopBase, rec

import engine  # noqa: E402  (test_loop put skills/task-loop on sys.path)
import loop  # noqa: E402
import tl  # noqa: E402

POSIX = os.name != "nt"
REAL_PREPARE = loop.prepare  # LoopBase stubs it


def sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


class Slots(LoopBase):
    def setUp(self):
        super().setUp()
        self.kids = []
        for n in ("s1", "s2"):
            (self.repo / ".slots" / n).mkdir(parents=True)

    def tearDown(self):
        for k in self.kids:
            k.kill()
            k.wait()
        super().tearDown()

    def slot(self, n):
        return str(self.repo / ".slots" / n)

    def live_lock(self, n, bead="x-9"):
        k = sleeper()
        self.kids.append(k)
        f = tl.engine_lock_path(self.slot(n))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"pid": k.pid, "bead": bead, "started": time.time()}))
        return k

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = tl.main(list(args))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def run_task(self, bead_id, slot=None, worktree=None, engine_run=None, **env):
        """engine.main as `tl run-task` calls it, with the engine itself stubbed: engine_run(eng) is its run()."""
        f = Path(self.home, "out-%s.json" % bead_id)
        a = engine.Args(id=bead_id, worktree=worktree, slot=slot, dry_run=False, fresh=False, quiet=True,
                        outcome_file=str(f))
        made = mock.Mock()
        made.return_value.run.side_effect = lambda: (engine_run or (lambda: 0))()
        made.return_value.result.return_value = {"outcome": "landed", "bead": bead_id}
        made.return_value.log_path = Path(self.home, "e.jsonl")
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(engine, "reclaim", return_value=(True, "")), \
                mock.patch.object(tl, "cmd_claim", return_value=0), mock.patch.object(engine, "Engine", made), \
                mock.patch.object(signal, "signal"), redirect_stdout(out):
            rc = engine.main(a)
        self.made = made
        return rc, json.loads(f.read_text()), out.getvalue()


class RunTaskTakesItsSlot(Slots):
    def test_a_hand_run_holds_the_slot_bead_while_it_runs_and_the_loop_takes_another(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        seen = {}

        def during():  # the loop starts while the hand run is mid-bead (2026-10-21 18:17)
            bd.beads["x-1"].update(status="in_progress", assignee=tl.actor())  # run-task's claim (stubbed here)
            seen["slot"] = dict(bd.slots["sl-1"])
            seen["lock"] = tl.engine_lock_path(self.slot("s1")).exists()
            seen["env"] = os.environ.get("TASK_LOOP_SLOT_BEAD")
            seen["list"] = self.cli("slot", "list")[1]
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-loop0000"}):
                self.run_loop("--max-beads", "1")
            return 0
        rc, r, _ = self.run_task("x-1", slot="s1", worktree=self.slot("s1"), engine_run=during)
        self.assertEqual(rc, 0)
        self.assertEqual((seen["slot"]["status"], seen["slot"]["assignee"]), ("in_progress", tl.actor()))
        self.assertTrue(seen["lock"])
        self.assertEqual(seen["env"], "sl-1")  # the engine heartbeats it
        self.assertIn("run-task x-1", seen["list"])
        self.assertEqual(self.started, [("x-2", "s2")])
        # released at the end, the lock gone
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))
        self.assertFalse(tl.engine_lock_path(self.slot("s1")).exists())

    def test_slot_alone_runs_in_the_slots_worktree(self):
        self.beads({"x-1": []})
        self.run_task("x-1", slot="s1")
        self.assertEqual(self.made.call_args[0][1], str(Path(self.slot("s1")).resolve()))

    def test_run_task_refuses_a_slot_another_session_holds(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000",
                                metadata={"held_by": "tl-loop0000", "held_since": "2026-10-21T18:17:00"})
        rc, r, out = self.run_task("x-1", slot="s1")
        self.assertEqual((rc, r["outcome"]), (1, "taken"))
        self.assertIn("slot s1 held by tl-loop0000 since 2026-10-21T18:17", r["why"])
        self.made.assert_not_called()
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-loop0000")  # never released by the refused run

    def test_run_task_refuses_a_held_slot(self):
        bd = self.beads({"x-1": []})
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
            self.assertEqual(self.cli("slot", "hold", "s1", "--why", "screenshots")[0], 0)
        bd.slots["sl-1"].update(status="open", assignee="")  # the holder's lease lapsed and reclaim freed the bead
        rc, r, _ = self.run_task("x-1", slot="s1")
        self.assertEqual(r["outcome"], "taken")
        self.assertIn("slot s1 held by tl-denis000", r["why"])
        self.assertIn("screenshots", r["why"])

    def test_the_slot_is_released_when_the_run_is_stopped_before_the_engine_ran(self):
        bd = self.beads({"x-1": []})

        def stopped(*a, **kw):
            raise engine.Blocked("failed: stopped (SIGTERM)")
        with mock.patch.object(engine, "reclaim", side_effect=stopped):
            f = Path(self.home, "o.json")
            a = engine.Args(id="x-1", worktree=None, slot="s1", dry_run=False, fresh=False, quiet=True,
                            outcome_file=str(f))
            with mock.patch.object(signal, "signal"), redirect_stdout(io.StringIO()):
                rc = engine.main(a)
        self.assertNotEqual(rc, 0)
        self.assertEqual(json.loads(f.read_text())["outcome"], "failed")
        self.assertEqual(bd.slots["sl-1"]["status"], "open")
        self.assertFalse(tl.engine_lock_path(self.slot("s1")).exists())

    def test_a_run_the_loop_started_does_not_take_or_release_the_slot_again(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee=tl.actor())
        self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-1")
        self.assertEqual(bd.slots["sl-1"]["status"], "in_progress")
        self.assertNotIn(("unclaim", "sl-1"), bd.calls)
        self.assertNotIn(("update", "sl-1", "--claim"), bd.calls)

    def test_run_task_refuses_a_worktree_with_a_live_engine(self):
        self.beads({"x-1": []})
        k = self.live_lock("s1", bead="x-0")
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        self.assertEqual(r["outcome"], "taken")
        self.assertIn("pid %d" % k.pid, r["why"])
        self.made.assert_not_called()
        self.assertTrue(tl.engine_lock_path(self.slot("s1")).exists())  # never removes another run's lock

    def test_a_dead_engines_lock_is_no_obstacle(self):
        self.beads({"x-1": []})
        k = self.live_lock("s1")
        k.kill()
        k.wait()
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        self.assertEqual(rc, 0)


class LiveEngineBackstop(Slots):
    def test_the_loop_skips_a_slot_whose_worktree_has_a_live_engine_though_its_bead_is_open(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.live_lock("s1")
        self.run_loop("--max-beads", "1")
        self.assertEqual(self.started, [("x-1", "s2")])
        self.assertEqual(bd.slots["sl-1"]["status"], "open")

    def test_a_live_worker_left_by_a_dead_engine_keeps_the_slot_busy(self):
        self.beads({"x-1": [rec("landed")]})
        k = sleeper()
        self.kids.append(k)
        f = tl.engine_lock_path(self.slot("s1"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"pid": 0, "bead": "x-0", "workers": [k.pid]}))
        self.assertIn(str(k.pid), tl.engine_busy(self.slot("s1")))
        self.run_loop("--max-beads", "1")
        self.assertEqual(self.started, [("x-1", "s2")])

    def test_slot_reset_never_touches_a_slot_with_a_live_engine(self):
        self.beads({})
        self.live_lock("s1")
        with mock.patch.object(tl, "git", side_effect=AssertionError("git ran in a live slot")):
            rc, out = self.cli("slot", "reset", "s1", "--bead", "x-1")
        self.assertEqual(rc, 4)
        self.assertIn("BUSY", out)
        with mock.patch.object(tl, "git", side_effect=AssertionError("git ran in a live slot")), \
                redirect_stdout(io.StringIO()):
            self.assertNotEqual(REAL_PREPARE(str(self.repo), "s1", "x-1"), 0)

    def test_slot_list_shows_the_live_engine(self):
        self.beads({})
        k = self.live_lock("s1", bead="x-7")
        out = self.cli("slot", "list")[1]
        line = [ln for ln in out.splitlines() if ln.startswith("s1")][0]
        self.assertIn("engine pid %d" % k.pid, line)
        self.assertIn("x-7", line)


class Hold(Slots):
    def test_a_hold_is_skipped_by_the_loop_shown_in_list_and_expires(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        t = [time.time()]
        with mock.patch.object(tl, "now", lambda: t[0]):
            rc, out = self.cli("slot", "hold", "s1", "--why", "screenshots for the owner", "--for", "30")
            self.assertEqual(rc, 0, out)
            bd.slots["sl-1"].update(status="open", assignee="")  # a lapsed lease does not end a hold
            listing = self.cli("slot", "list")[1]
            self.assertIn("screenshots for the owner", listing)
            self.assertIn(tl.actor(), [ln for ln in listing.splitlines() if ln.startswith("s1")][0])
            self.run_loop("--max-beads", "1")
            self.assertEqual(self.started, [("x-1", "s2")])
            t[0] += 31 * 60  # expired
            self.run_loop("--max-beads", "1")
        self.assertEqual(self.started[-1], ("x-2", "s1"))

    def test_hold_default_is_an_hour_and_renewing_extends_it(self):
        bd = self.beads({})
        t = [1_800_000_000.0]
        with mock.patch.object(tl, "now", lambda: t[0]):
            self.cli("slot", "hold", "s1", "--why", "a person")
            until = float(bd.slots["sl-1"]["metadata"]["hold_until"])
            self.assertAlmostEqual(until - t[0], 3600, delta=1)
            t[0] += 1800
            self.assertEqual(self.cli("slot", "hold", "s1", "--why", "a person")[0], 0)
            self.assertAlmostEqual(float(bd.slots["sl-1"]["metadata"]["hold_until"]) - t[0], 3600, delta=1)

    def test_release_ends_a_hold(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.cli("slot", "hold", "s1", "--why", "screenshots")
        self.assertEqual(self.cli("slot", "release", "s1")[0], 0)
        self.assertEqual(bd.slots["sl-1"]["status"], "open")
        self.assertNotIn("hold_until", bd.slots["sl-1"].get("metadata", {}))
        self.run_loop("--max-beads", "1")
        self.assertEqual(self.started, [("x-1", "s1")])

    def test_a_slot_in_use_cannot_be_held(self):
        bd = self.beads({})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000")
        rc, out = self.cli("slot", "hold", "s1", "--why", "x")
        self.assertNotEqual(rc, 0)
        self.assertIn("tl-loop0000", out)
        self.live_lock("s2")
        self.assertNotEqual(self.cli("slot", "hold", "s2", "--why", "x")[0], 0)

    def test_release_refuses_a_slot_with_a_live_engine(self):
        bd = self.beads({})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-hand0000")
        self.live_lock("s1")
        rc, _ = self.cli("slot", "release", "s1")
        self.assertNotEqual(rc, 0)
        self.assertEqual(bd.slots["sl-1"]["status"], "in_progress")


ROUTE = textwrap.dedent('''
    import os, signal, subprocess, sys, time
    w = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
                         start_new_session=True)
    open(sys.argv[1], "w").write(str(w.pid))
    def bye(*_):
        if sys.argv[2] == "kills":
            os.killpg(w.pid, 9)
            sys.exit(143)
    signal.signal(signal.SIGTERM, bye)
    while True:
        time.sleep(0.1)
''')


@unittest.skipUnless(POSIX, "process groups")
class StoppedEngineKillsItsWorker(unittest.TestCase):
    """delegate's route.py runs the worker in its own process group: a SIGKILL to route.py's group orphaned the 5ar.7
    writer, which kept editing the slot after its engine stopped (2026-10-21)."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "route.py").write_text(ROUTE)

    def tearDown(self):
        self.tmp.cleanup()

    def worker_pid(self):
        f = self.d / "w.pid"
        for _ in range(100):
            if f.exists() and f.read_text():
                return int(f.read_text())
            time.sleep(0.05)
        self.fail("no worker")

    def gone(self, pid):
        for _ in range(60):
            if not tl.pid_alive(pid) or zombie(pid):
                return True
            time.sleep(0.05)
        return False

    def stop_during(self, mode, how):
        cmd = [sys.executable, str(self.d / "route.py"), str(self.d / "w.pid"), mode]
        log = self.d / "err.log"
        if how == "timeout":
            with mock.patch.object(engine, "STOP_GRACE", 1):
                res, _ = engine.run_proc(cmd, str(self.d), 1.5, log)
            self.assertIsNone(res)
            return
        old = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(engine.Blocked("failed: stopped (SIGTERM)")))
        t = __import__("threading").Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGTERM))
        t.start()
        try:
            with mock.patch.object(engine, "STOP_GRACE", 1), self.assertRaises(engine.Blocked):
                engine.run_proc(cmd, str(self.d), 60, log)
        finally:
            t.cancel()
            signal.signal(signal.SIGTERM, old)

    def test_a_stop_lets_route_py_end_its_worker(self):
        self.stop_during("kills", "sigterm")
        self.assertTrue(self.gone(self.worker_pid()))

    def test_a_route_py_that_ignores_the_stop_still_loses_its_worker(self):
        self.stop_during("ignores", "sigterm")
        self.assertTrue(self.gone(self.worker_pid()))

    def test_a_node_timeout_kills_the_worker_too(self):
        self.stop_during("ignores", "timeout")
        self.assertTrue(self.gone(self.worker_pid()))


def zombie(pid):
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip().startswith("Z")


if __name__ == "__main__":
    unittest.main()
