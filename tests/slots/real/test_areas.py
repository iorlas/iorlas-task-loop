"""Areas (tl-bxk.11.4): two concurrent beads never work the same area; the queue skips a bead whose area runs elsewhere.
The slot line (tl-bxk.11.5): waiters for a slot are served in arrival order; a dead waiter never blocks the line."""

import datetime
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # python3 -m unittest tests.test_areas, from the repo root
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from loop.test_loop import rec

# isort: split
from support import (
    looptest,
    tlbd,
)
from support import slots as sl
from support.narrow import must

from slots.test_slots import Slots
from taskloop.adapters import ident
from taskloop.app.launch import loop as wloop
from taskloop.app.loop.core import Core
from taskloop.app.loop.queue import QueueRule
from taskloop.app.run import (
    entry,
)
from taskloop.app.slots import (
    engine_lock,
    marks,
)
from taskloop.app.slots import line as slots_line
from taskloop.app.track import verbs
from taskloop.app.wire import slots as wslots
from taskloop.contracts import paths
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.ids import loop_key
from taskloop.stores.files import FileTickets

LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"

HERE = Path(__file__).resolve().parents[3] / "skills" / "task-loop"
AREAS_JSON = {"area_label_prefix": "lane:", "areas": {"core": ["e-core"], "build": ["build"]}}


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


class AreasBase(Slots):
    def setUp(self):
        super().setUp()
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}, "engine": AREAS_JSON}))

    def lanes(self, script, lanes, slots=2):
        bd = self.beads(script, slots=slots)
        for b, lane in lanes.items():
            bd.beads[b]["labels"] = ["lane:" + lane]
        return bd

    def running(self, bd, b, slot="s1", sb="sl-1"):
        """b runs in slot: its claim, the slot bead held for it."""
        bd.beads[b].update(status="in_progress", assignee="tl-other")
        bd.slots[sb].update(status="in_progress", assignee="tl-other", metadata={"held_by": "tl-other", "held_bead": b})

    def order(self):
        ranked, skipped = looptest.queue(str(self.repo))
        return [b.id for b, _ in ranked], dict(skipped)


class Areas(AreasBase):
    def test_the_queue_skips_a_bead_whose_area_runs_in_another_slot_and_keeps_the_order_of_the_rest(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": [], "x-4": []}, {"x-1": "live", "x-2": "live", "x-3": "shell"})
        self.running(bd, "x-1")
        ids, skipped = self.order()
        self.assertEqual(ids, ["x-3", "x-4"])
        self.assertEqual(skipped, {"x-2": "area live busy: x-1 in s1"})
        _rc, out = self.cli("next", "--repo", str(self.repo))
        self.assertIn("NEXT x-3", out)
        self.assertIn("skip x-2: area live busy: x-1 in s1", out)
    def test_a_live_engine_lock_naming_a_bead_makes_its_area_busy_a_dead_one_does_not(self):
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        bd.beads["x-1"].update(status="in_progress", assignee="denis")
        k = self.live_lock("s2", bead="x-1")  # a run whose slot bead says nothing (an older engine, a --worktree run)
        self.assertEqual(self.order(), ([], {"x-2": "area live busy: x-1 in s2"}))
        k.kill()
        k.wait()
        self.assertEqual(self.order()[0], ["x-2"])

    def test_the_area_is_free_again_once_the_running_bead_ends(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": [rec("landed")]}, {"x-1": "live", "x-2": "live", "x-3": "shell"})
        seen = {}

        def during():  # a second loop starts while x-1 runs in s1 by hand
            bd.beads["x-1"].update(status="in_progress", assignee=ident.actor())  # run-task's claim (stubbed here)
            seen["queue"] = self.order()
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-loop0000"}):
                self.run_loop("--max-beads", "1")
            return 0
        rc, _r, _ = self.run_task("x-1", slot="s1", engine_run=during)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["queue"], (["x-3"], {"x-2": "area live busy: x-1 in s1"}))
        self.assertEqual(self.started, [("x-3", "s2")])  # the other area's bead, never x-2 beside x-1
        bd.beads["x-1"]["status"] = "closed"
        self.assertEqual(self.order(), (["x-2"], {}))
        self.assertNotIn("held_bead", bd.slots["sl-1"].get("metadata") or {})  # the slot's release clears the mark

    def test_the_claim_checks_the_area_again_under_the_area_lock(self):
        """Two loops read the queue at once: both see the area free; the claim re-checks under one lock."""
        bd = self.lanes({"x-1": [rec("landed")], "x-2": [rec("landed")]}, {"x-1": "live"})
        real, calls = QueueRule.busy_areas, []

        def busy(*a, **kw):
            calls.append(1)
            if len(calls) == 2:  # the first claim: another loop marked x-9 of live just now
                return {"live": ("x-9", "s2")}
            return real(*a, **kw)
        with mock.patch.object(QueueRule, "busy_areas", autospec=True, side_effect=busy):
            self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual(self.started, [("x-2", "s1")])
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        self.assertFalse([c for c in bd.calls if c[:1] == ("update",) and c[1:2] == ("x-1",) and "--claim" in c])

    def test_the_loop_marks_its_slot_with_the_bead_it_runs(self):
        bd = self.lanes({"x-1": [rec("landed")]}, {"x-1": "live"})
        seen = {}
        self.during.append(lambda: seen.update(meta=dict(bd.slots["sl-1"].get("metadata") or {}),
                                               lock=engine_lock.read_engine_lock(self.slot("s1"))))
        self.run_loop()
        self.assertEqual(seen["meta"].get("held_bead"), "x-1")
        self.assertEqual(seen["lock"].get("bead"), "x-1")

    def test_a_failed_bead_gives_back_its_slot_and_its_area_so_the_loop_goes_on(self):
        """tl-bjd: w-5 of the race failed and its area stayed busy. The slot's release clears the bead's mark, whatever the outcome."""
        bd = self.lanes({"x-1": [rec("failed")], "x-2": [rec("landed")]}, {"x-1": "live", "x-2": "live"}, slots=1)
        self.assertEqual(self.run_loop("--max-beads", "2"), 0)
        self.assertEqual(self.started, [("x-1", "s1"), ("x-2", "s1")])  # x-2 is of the failed bead's area, in the failed bead's slot
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))
        self.assertFalse(set(bd.slots["sl-1"].get("metadata") or {}) & set(marks.HELD_KEYS))

    def test_when_every_ready_bead_waits_for_its_area_the_loop_waits_instead_of_draining(self):
        bd = self.lanes({"x-1": [], "x-2": [rec("landed")]}, {"x-1": "live", "x-2": "live"})
        self.running(bd, "x-1")

        def nap(secs, *a, **kw):
            self.clock.naps.append(round(secs))
            self.clock.t += secs
            bd.beads["x-1"].update(status="closed", assignee="")  # x-1 ends
            bd.slots["sl-1"].update(status="open", assignee="", metadata={})
        with mock.patch.object(Core, "nap", staticmethod(nap)):
            self.assertEqual(self.run_loop(), 0)
        self.assertIn(round(LoopConfig().area_poll), self.clock.naps)
        self.assertEqual([b for b, _ in self.started], ["x-2"])
        self.assertIn("area", self.out)

    def test_a_mark_a_reclaim_left_on_a_slot_bead_is_cleared_by_the_next_take(self):
        """bd reclaim frees a dead loop's slot bead but keeps its metadata: a hold or a loop's take there must not
        leave the old bead running in its area."""
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        bd.beads["x-1"]["status"] = "closed"
        bd.slots["sl-1"]["metadata"] = {"held_bead": "x-1"}  # open, as reclaim left it
        self.assertEqual(self.cli("slot", "hold", "s1", "--why", "screenshots")[0], 0)
        self.assertEqual(wloop.running(str(self.repo)), {})
        self.assertEqual(self.order(), (["x-2"], {}))
        bd.slots["sl-2"]["metadata"] = {"held_bead": "x-1"}
        self.assertEqual(must(sl.take_slot(str(self.repo), self.cfg_slots()))[0], "s2")
        self.assertEqual(wloop.running(str(self.repo)), {})

    def cfg_slots(self):
        return wslots.profile_slots(str(self.repo))

    def test_a_hand_run_in_a_busy_area_warns_and_runs(self):
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        self.running(bd, "x-1")
        rc, r, out = self.run_task("x-2", slot="s2")
        self.assertEqual((rc, r["outcome"]), (0, "landed"))
        self.assertIn("area live busy: x-1 in s1", out)
        self.assertIn("--exclusive-area", out)
        self.made.assert_called()

    def test_exclusive_area_refuses_a_hand_run_in_a_busy_area_and_gives_the_slot_back(self):
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        self.running(bd, "x-1")
        rc, r, _out = self.run_task("x-2", slot="s2", flags={"exclusive_area": True})
        self.assertEqual((rc, r["outcome"]), (1, "taken"))
        self.assertIn("area live busy: x-1 in s1", r["why"])
        self.made.assert_not_called()
        self.assertEqual((bd.slots["sl-2"]["status"], bd.slots["sl-2"]["assignee"]), ("open", ""))
        self.assertFalse(engine_lock.engine_lock_path(self.slot("s2")).exists())

    def test_a_hand_run_in_a_free_area_or_with_no_area_says_nothing(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": []}, {"x-1": "live", "x-2": "shell"})
        self.running(bd, "x-1")
        for b in ("x-2", "x-3"):
            _rc, r, out = self.run_task(b, slot="s2", flags={"exclusive_area": True})
            self.assertEqual(r["outcome"], "landed", out)
            self.assertNotIn("area", out)


class Line(Slots):
    """The slot line: tickets under the repo's slot state, served first come first."""

    def setUp(self):
        super().setUp()
        self.cfg = wslots.profile_slots(str(self.repo))

    def tickets(self):
        return list(sl.ticket_dir(str(self.repo)).glob("*.json"))

    def waiter(self, label, served):
        def go():
            got = wslots.wait_slot(str(self.repo), self.cfg, label, poll=(0.01, 0.02))
            served.append((label, got[0] if got else None))
            assert got
            wslots.release_slot(str(self.repo), got[0])
        th = threading.Thread(target=go, daemon=True)
        th.start()
        return th

    def until(self, cond, secs=60):
        end = time.monotonic() + secs
        while time.monotonic() < end and not cond():
            time.sleep(0.01)
        self.assertTrue(cond())
    def test_a_waiter_behind_a_live_ticket_never_takes_a_free_slot_and_a_killed_waiter_does_not_block(self):
        self.beads({}, slots=1)
        k = subprocess.Popen(["sleep", "60"])  # a live pid for the first in line
        self.kids.append(k)
        FileTickets(paths.ConfigDir(ident.config_dir())).take(loop_key(str(self.repo)), "first", 2, pid=k.pid, now=time.time())
        tries = []
        got = wslots.wait_slot(str(self.repo), self.cfg, "second", poll=(0.01, 0.01),
                           stop=lambda: tries.append(1) or len(tries) >= 5)
        self.assertIsNone(got)  # the slot is free, but the first in line is alive
        self.assertEqual(len(self.tickets()), 1)  # its own ticket gone, the first one's kept
        k.kill()
        k.wait()
        got = wslots.wait_slot(str(self.repo), self.cfg, "second", poll=(0.01, 0.01), stop=lambda: True)
        self.assertEqual(must(got)[0], "s1")
        self.assertEqual(self.tickets(), [])  # the dead waiter's ticket was dropped


    def test_run_task_slot_any_takes_a_free_slot_and_gives_it_back(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        rc, r, _ = self.run_task("x-1", slot="any")
        self.assertEqual((rc, r["outcome"]), (0, "landed"))
        self.assertEqual(self.made.call_args[0][1], str(Path(self.slot("s2")).resolve()))
        self.assertEqual((bd.slots["sl-2"]["status"], bd.slots["sl-2"]["assignee"]), ("open", ""))
        self.assertEqual(self.tickets(), [])

    def test_run_task_slot_any_without_wait_refuses_when_none_is_free(self):
        bd = self.beads({"x-1": []}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        rc, r, _out = self.run_task("x-1", slot="any")
        self.assertEqual((rc, r["outcome"]), (1, "taken"))
        self.assertIn("no free slot", r["why"])
        self.made.assert_not_called()
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-other")
        self.assertEqual(self.tickets(), [])

    def test_run_task_slot_any_wait_gets_the_slot_once_it_frees(self):
        bd = self.beads({"x-1": []}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        threading.Timer(0.2, lambda: bd.slots["sl-1"].update(status="open", assignee="")).start()
        with mock.patch.object(slots_line, "TICKET_POLL", (0.01, 0.05)):
            rc, r, out = self.run_task("x-1", slot="any", flags={"wait": True})
        self.assertEqual((rc, r["outcome"]), (0, "landed"), out)
        self.assertEqual(self.made.call_args[0][1], str(Path(self.slot("s1")).resolve()))
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))

    def test_the_loop_waits_in_the_line_too(self):
        self.beads({"x-1": [rec("landed")]}, slots=1)
        first = sl.take_ticket(str(self.repo), "a hand run waiting before the loop came")
        naps = []

        def nap(secs, *a, **kw):
            naps.append(secs)
            self.clock.t += secs
            if len(naps) == 3:
                sl.drop_ticket(self.repo, first)  # served (or gone)
        with mock.patch.object(Core, "nap", staticmethod(nap)):
            self.assertEqual(self.run_loop(), 0)
        self.assertGreaterEqual(len(naps), 3)  # the slot was free all along: the loop waited its turn
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertIn("in line", self.out)


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(AreasBase):
    """Review of the areas and the slot line: the expired-hold clean-up, release by the holder only, an unreadable
    holder, a ticket without seq, a long area wait, two exclusive hand runs."""

    def expired(self, bd, sb="sl-1"):
        bd.slots[sb].update(status="in_progress", assignee="tl-old", metadata={
            "held_by": "tl-old", "held_since": "2026-10-21T10:00:00", "held_why": "screenshots", "hold_until": "1"})


    def test_an_unreadable_holder_makes_every_area_busy_and_is_logged(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": [], "x-4": []}, {"x-1": "live", "x-2": "live", "x-3": "shell"})
        self.running(bd, "x-1")
        real_bd, err = bd, io.StringIO()

        def bd_x1_unreadable(*a, **kw):  # bd answers nothing parseable for x-1 only
            return tlbd.done("") if a[:2] == ("show", "x-1") else real_bd(*a, **kw)
        with tlbd.bd_boundary(bd_x1_unreadable):
            ranked, skip = looptest.queue(str(self.repo), say=err.write)
        ids, skipped = [b.id for b, _ in ranked], dict(skip)
        self.assertEqual(ids, ["x-4"])  # a bead of no area is unrestricted
        self.assertIn("area live busy: x-1 in s1", skipped["x-2"])
        self.assertIn("area shell busy: x-1 in s1", skipped["x-3"])
        self.assertIn("x-1", err.getvalue())


    def test_a_long_area_wait_says_how_long_and_who_holds_it_and_until_still_ends_the_loop(self):
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        self.running(bd, "x-1")  # a hung but live holder
        until = (datetime.datetime.fromtimestamp(self.clock()) + datetime.timedelta(minutes=25)).strftime("%H:%M")
        self.assertEqual(self.run_loop("--until", until), 0)
        self.assertIn("waiting 10 min on area live held by x-1 in s1", self.out)
        self.assertIn("waiting 20 min on area live held by x-1 in s1", self.out)
        self.assertIn("reached", self.out)
        self.assertEqual(self.started, [])

    @NO_FCNTL
    def test_two_exclusive_hand_runs_in_one_area_let_the_first_in_win(self):
        self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        outs, real, gate, done = {}, entry.take_area, threading.Barrier(2, timeout=60), threading.Barrier(2, timeout=60)

        def area(*a, **kw):  # both runs hold their slots before either decides, and neither lets go before both did
            gate.wait()
            try:
                return real(*a, **kw)
            finally:
                done.wait()

        def run(b, slot):
            f = Path(self.home, f"out-{b}.json")
            a = entry.Args(id=b, worktree=None, slot=slot, dry_run=False, fresh=False, quiet=True,
                            outcome_file=str(f), exclusive_area=True)
            entry.main(a)
            outs[b] = json.loads(f.read_text())["outcome"]
        made = mock.Mock()
        made.return_value.run.return_value = 0
        made.return_value.result.side_effect = lambda: {"outcome": "landed"}
        made.return_value.log_path = Path(self.home, "e.jsonl")
        with mock.patch.object(entry, "reclaim", return_value=(True, "")), mock.patch.object(verbs, "claim", return_value=0), \
                mock.patch.object(entry, "Engine", made), mock.patch.object(signal, "signal"), \
                mock.patch.object(entry, "take_area", side_effect=area), redirect_stdout(io.StringIO()):
            ths = [threading.Thread(target=run, args=("x-1", "s1")), threading.Thread(target=run, args=("x-2", "s2"))]
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)
        self.assertEqual(sorted(outs.values()), ["landed", "taken"], outs)
