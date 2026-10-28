"""A hand run and a loop never share a slot (tl-bxk.9.5): run-task --slot takes the slot bead, a live engine in a slot's
worktree keeps it busy whatever its bead says, a hold reserves a slot for a person, and a stopped engine's worker dies
with it."""

import dataclasses
import io
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -m unittest tests.test_slots, from the repo root
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from test_loop import LoopBase, rec  # noqa: E402  (puts skills/task-loop on sys.path)
from support import slots as sl  # noqa: E402
from support import tlbd  # noqa: E402

import engine  # noqa: E402  (test_loop put skills/task-loop on sys.path)
import loop_env  # noqa: E402
from taskloop.app.loop.take import Taker  # noqa: E402
import tl  # noqa: E402
from support.fakes import as_bead  # noqa: E402
from taskloop.app.slots import marks  # noqa: E402
from taskloop.contracts.config import SlotsConfig  # noqa: E402

POSIX = os.name != "nt"
REAL_PREPARE = Taker.prepare  # LoopBase stubs it


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


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

    def run_task(self, bead_id, slot=None, worktree=None, engine_run=None, flags=None, **env):
        """engine.main as `tl run-task` calls it, with the engine itself stubbed: engine_run(eng) is its run(). flags:
        more run-task options (wait, exclusive_area)."""
        f = Path(self.home, "out-%s.json" % bead_id)
        a = engine.Args(id=bead_id, worktree=worktree, slot=slot, dry_run=False, fresh=False, quiet=True,
                        outcome_file=str(f), **(flags or {}))
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


class SlotListShowsTheLine(Slots):
    def test_slot_list_names_the_waiters_in_the_order_they_are_served(self):
        """tl-43k: P0 first, then arrival; the list says so."""
        self.beads({"x-1": []})
        a, b = sl.take_ticket(self.repo, "run-task late-p2", 2), sl.take_ticket(self.repo, "run-task hclf.34", 0)
        try:
            rc, out = self.cli("slot", "list")
        finally:
            sl.drop_ticket(self.repo, a)
            sl.drop_ticket(self.repo, b)
        rows = [x.split("\t") for x in out.splitlines() if x.startswith("WAITING")]
        self.assertEqual([(r[1], r[2], r[4]) for r in rows], [("1", "P0", "run-task hclf.34"), ("2", "P2", "run-task late-p2")])


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
        self.beads({"x-1": []})
        self.live_lock("s1")
        with mock.patch.object(tl, "git", side_effect=AssertionError("git ran in a live slot")):
            rc, out = self.cli("slot", "reset", "s1", "--bead", "x-1")
        self.assertEqual(rc, 4)
        self.assertIn("BUSY", out)
        senv = loop_env.build(str(self.repo)).slot_env()  # the profile read is git too: read it before the patch
        env = dataclasses.replace(loop_env.build(str(self.repo)), slot_env=lambda: senv)
        with mock.patch.object(tl, "git", side_effect=AssertionError("git ran in a live slot")), \
                redirect_stdout(io.StringIO()):
            self.assertIsNotNone(REAL_PREPARE(Taker(env, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), {}), "s1", "x-1"))

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


@unittest.skipUnless(POSIX, "ps start times and zombies")
class StaleLocks(Slots):
    """A lock outlives a SIGKILLed engine: its pid may be reused or a zombie; neither keeps the slot busy forever."""

    def test_a_reused_pid_with_another_start_time_is_dead(self):
        k = sleeper()
        self.kids.append(k)
        f = tl.engine_lock_path(self.slot("s1"))
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"pid": k.pid, "start": "Mon Jan  1 00:00:00 2001", "bead": "x-0"}))
        self.assertEqual(tl.engine_busy(self.slot("s1")), "")
        f.write_text(json.dumps({"pid": k.pid, "start": tl.proc_start(k.pid), "bead": "x-0"}))
        self.assertIn("pid %d" % k.pid, tl.engine_busy(self.slot("s1")))
        f.write_text(json.dumps({"pid": 0, "workers": [[k.pid, "Mon Jan  1 00:00:00 2001"]]}))
        self.assertEqual(tl.engine_busy(self.slot("s1")), "")

    def test_a_zombie_is_dead(self):
        z = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            for _ in range(100):
                if not tl.pid_alive(z.pid):
                    break
                time.sleep(0.05)
            self.assertFalse(tl.pid_alive(z.pid))  # exited and not yet reaped: stream-proc reads it as gone
            f = tl.engine_lock_path(self.slot("s1"))
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps({"pid": z.pid, "bead": "x-0"}))
            self.assertEqual(tl.engine_busy(self.slot("s1")), "")
        finally:
            z.wait()

    def test_busy_names_the_lock_and_force_drops_it_on_reset_and_release(self):
        self.beads({})
        k = self.live_lock("s1")
        rc, out = self.cli("slot", "reset", "s1")
        self.assertEqual(rc, 4)
        self.assertIn(str(tl.engine_lock_path(self.slot("s1"))), out)
        self.assertIn(str(k.pid), out)
        rc, out = self.cli("slot", "reset", "s1", "--force")
        self.assertNotEqual(rc, 4)
        self.assertIn("FORCED", out)
        self.assertFalse(tl.engine_lock_path(self.slot("s1")).exists())
        self.live_lock("s2")
        self.assertEqual(self.cli("slot", "release", "s2", "--force")[0], 0)
        self.assertFalse(tl.engine_lock_path(self.slot("s2")).exists())


class SameActor(Slots):
    """A hand run from the session that started the loop shares the loop's actor: bd lets it re-claim the slot bead."""

    def test_a_held_slot_bead_is_refused_to_its_own_actor_unless_it_is_the_runs_own_slot_bead(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee=tl.actor(),
                                metadata={"held_by": tl.actor(), "held_since": "2026-10-21T18:17:00",
                                          "held_why": "tl loop"})
        rc, r, _ = self.run_task("x-1", slot="s1")
        self.assertEqual(r["outcome"], "taken")
        self.assertIn("slot s1 held by %s since 2026-10-21T18:17:00 (tl loop)" % tl.actor(), r["why"])
        rc, r, _ = self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-2")  # another slot's bead: no pass
        self.assertEqual(r["outcome"], "taken")
        rc, r, _ = self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-1")
        self.assertEqual(rc, 0)

    def test_a_hand_run_with_only_a_worktree_that_is_a_slot_takes_that_slot(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000")
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        self.assertEqual(r["outcome"], "taken")
        self.assertIn("held by tl-loop0000", r["why"])
        bd.slots["sl-1"].update(status="open", assignee="")
        seen = {}
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"),
                                 engine_run=lambda: seen.update(bd.slots["sl-1"]) or 0)
        self.assertEqual((rc, seen["status"]), (0, "in_progress"))
        self.assertEqual(bd.slots["sl-1"]["status"], "open")

    def test_the_loop_locks_the_slot_from_its_take_through_the_reset(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": []})
        seen = {}

        def reset(taker, slot, bead_id):
            seen["lock"] = tl.read_engine_lock(self.slot(slot))
            hand = os.getpid() + 1  # another process of this very session (same actor)
            with mock.patch.dict(os.environ, {"TASK_LOOP_SLOT_BEAD": ""}), mock.patch.object(os, "getpid", return_value=hand):
                bd.slots["sl-1"]["status"] = "open"  # even were its bead open
                rc, r, _ = self.run_task("x-2", worktree=self.slot(slot))
                bd.slots["sl-1"].update(status="in_progress", assignee=tl.actor())
            seen["hand"] = r
        with mock.patch.object(Taker, "prepare", reset):
            self.run_loop("--max-beads", "1")
        self.assertEqual((seen["lock"]["by"], seen["lock"]["pid"], seen["lock"]["slot_bead"]),
                         ("loop", os.getpid(), "sl-1"))
        self.assertEqual(seen["hand"]["outcome"], "taken")
        self.assertIn("loop pid %d" % os.getpid(), seen["hand"]["why"])
        self.assertFalse(tl.engine_lock_path(self.slot("s1")).exists())

    def test_the_loops_child_takes_over_its_lock_and_nobody_else_does(self):
        tl.write_engine_lock(self.slot("s1"), {"pid": os.getppid(), "start": tl.proc_start(os.getppid()), "by": "loop",
                                               "slot_bead": "sl-1"})
        with mock.patch.dict(os.environ, {"TASK_LOOP_SLOT_BEAD": "sl-1"}):
            self.assertEqual(tl.engine_busy(self.slot("s1"), handoff=True), "")
            self.assertTrue(tl.engine_busy(self.slot("s1")))
        with mock.patch.dict(os.environ, {"TASK_LOOP_SLOT_BEAD": "sl-2"}):
            self.assertTrue(tl.engine_busy(self.slot("s1"), handoff=True))


class HoldRaces(Slots):
    def test_a_hold_that_loses_the_claim_is_refused(self):
        bd = self.beads({})
        bd.taken_by_other.add("sl-1")
        rc, out = self.cli("slot", "hold", "s1", "--why", "x")
        self.assertEqual(rc, 1)
        self.assertIn("BUSY", out)
        self.assertNotIn("hold_until", bd.slots["sl-1"].get("metadata", {}))

    def test_an_expired_hold_gives_the_slot_bead_back(self):
        bd = self.beads({"x-1": [rec("landed")]})
        t = [time.time()]
        with mock.patch.object(tl, "now", lambda: t[0]):
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
                self.cli("slot", "hold", "s1", "--why", "a person", "--for", "10")
            self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("in_progress", "tl-denis000"))
            t[0] += 11 * 60
            self.run_loop("--max-beads", "1")
        self.assertEqual(self.started, [("x-1", "s1")])

    def test_releasing_a_slot_claimed_by_another_actor_frees_the_claim_too(self):
        # lifesim 0.23.34: `slot release --force` cleared the marks but the loop actor's claim kept the slot bead in_progress
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-551cf8ee")
        tl.release_slot(str(self.repo), "s1")
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-551cf8ee")  # without --force another actor's claim is left alone
        tl.release_slot(str(self.repo), "s1", force=True)
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))

    def test_an_expired_hold_frees_the_claim_of_the_loop_that_held_the_slot(self):
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-551cf8ee")
        bd.slots["sl-1"].setdefault("metadata", {}).update(held_by="tl-abcdef12-f296a9", hold_until="1000")
        sl.free_expired(str(self.repo))
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))

    @NO_FCNTL
    def test_a_hold_taken_while_the_loop_releases_the_slot_is_kept(self):
        # race test (tl-bxk.11.1): the release unclaimed the slot bead, a person's hold claimed it at once, and the
        # release's own clean-up then wiped the hold's metadata: the hold was gone, the slot only leased
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        real, holds = bd.__call__, []

        def hold():
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
                holds.append(self.cli("slot", "hold", "s1", "--why", "screenshots")[0])

        def racing(*a, **kw):  # the release runs under slot_lock: the hold waits for it, never lands in between
            r = real(*a, **kw)
            if a[:1] == ("unclaim",) and a[1] == "sl-1":
                th = threading.Thread(target=hold)
                th.start()
                th.join(0.3)
                self.assertEqual(holds, [])
                racing.th = th
            return r
        with tlbd.bd_boundary(racing):
            tl.release_slot(str(self.repo), "s1")
        racing.th.join(10)
        self.assertEqual(holds, [0])
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-denis000")
        self.assertIn("hold_until", bd.slots["sl-1"].get("metadata", {}))
        self.assertTrue(marks.hold_of(as_bead(bd.slots["sl-1"]), time.time()))

    def test_ones_own_hold_keeps_ones_own_runs_and_resets_off_unless_forced(self):
        self.beads({"x-1": []})
        self.cli("slot", "hold", "s1", "--why", "screenshots")
        rc, r, _ = self.run_task("x-1", slot="s1")
        self.assertEqual(r["outcome"], "taken")
        self.assertIn("screenshots", r["why"])
        self.assertEqual(self.cli("slot", "reset", "s1")[0], 4)
        self.assertNotEqual(self.cli("slot", "reset", "s1", "--force")[0], 4)


@unittest.skipUnless(POSIX, "process groups")
class NeverSignalOneself(unittest.TestCase):
    """A recorded or parsed pid or group id is a claim: no stop, reap or kill path may act on it when it is ours."""

    def test_stop_server_never_stops_the_calling_process(self):
        v = {"version": "1", "pid": os.getpid(), "urls": [], "started": 0}
        with mock.patch.object(tl.sproc, "stop_pid") as stop, mock.patch.object(tl, "ping", return_value=None):
            tl.stop_server(v)
        stop.assert_not_called()

    def test_run_main_leaves_no_sigterm_handler_behind(self):
        before = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(engine, "run_main_stoppable", return_value=0):
            engine.run_main(mock.Mock())
        self.assertIs(signal.getsignal(signal.SIGTERM), before)
