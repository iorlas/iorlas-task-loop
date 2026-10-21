"""Areas (tl-bxk.11.4): two concurrent beads never work the same area; the queue skips a bead whose area runs elsewhere.
The slot line (tl-bxk.11.5): waiters for a slot are served in arrival order; a dead waiter never blocks the line."""

import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -m unittest tests.test_areas, from the repo root
from test_loop import bead, rec  # noqa: E402
from test_slots import Slots  # noqa: E402

import loop  # noqa: E402
import tl  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "skills" / "task-loop"
AREAS = {"area_label_prefix": "lane:", "areas": {"core": ["e-core"], "build": ["build"]}}


class AreaOf(unittest.TestCase):
    def test_the_areas_map_first_then_the_label_prefix_first_match_wins_and_none_is_unrestricted(self):
        cache = {"e-core.1": "e-core", "e-core": None, "e-9": None}
        self.assertEqual(loop.area_of(bead("x-1", parent="e-core.1", labels=["lane:live"]), AREAS, cache), "core")
        self.assertEqual(loop.area_of(bead("x-2", labels=["lane:live", "lane:sim"]), AREAS, cache), "live")
        self.assertEqual(loop.area_of(bead("x-3", labels=["build"]), AREAS, cache), "build")
        self.assertEqual(loop.area_of(bead("x-4", parent="e-9", labels=["auto"]), AREAS, cache), "")
        self.assertEqual(loop.area_of(bead("x-5", labels=["lane:live"]), {}, cache), "")  # no area config: none


class Areas(Slots):
    def setUp(self):
        super().setUp()
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 2}, "engine": AREAS}))

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
        ranked, skipped = loop.queue(str(self.repo))
        return [b["id"] for b, _ in ranked], dict(skipped)

    def test_the_queue_skips_a_bead_whose_area_runs_in_another_slot_and_keeps_the_order_of_the_rest(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": [], "x-4": []}, {"x-1": "live", "x-2": "live", "x-3": "shell"})
        self.running(bd, "x-1")
        ids, skipped = self.order()
        self.assertEqual(ids, ["x-3", "x-4"])
        self.assertEqual(skipped, {"x-2": "area live busy: x-1 in s1"})
        rc, out = self.cli("next", "--repo", str(self.repo))
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
            bd.beads["x-1"].update(status="in_progress", assignee=tl.actor())  # run-task's claim (stubbed here)
            seen["queue"] = self.order()
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-loop0000"}):
                self.run_loop("--max-beads", "1")
            return 0
        rc, r, _ = self.run_task("x-1", slot="s1", engine_run=during)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["queue"], (["x-3"], {"x-2": "area live busy: x-1 in s1"}))
        self.assertEqual(self.started, [("x-3", "s2")])  # the other area's bead, never x-2 beside x-1
        bd.beads["x-1"]["status"] = "closed"
        self.assertEqual(self.order(), (["x-2"], {}))
        self.assertNotIn("held_bead", bd.slots["sl-1"].get("metadata") or {})  # the slot's release clears the mark

    def test_the_claim_checks_the_area_again_under_the_area_lock(self):
        """Two loops read the queue at once: both see the area free; the claim re-checks under one lock."""
        bd = self.lanes({"x-1": [rec("landed")], "x-2": [rec("landed")]}, {"x-1": "live"})
        real, calls = loop.busy_areas, []

        def busy(*a, **kw):
            calls.append(1)
            if len(calls) == 2:  # the first claim: another loop marked x-9 of live just now
                return {"live": ("x-9", "s2")}
            return real(*a, **kw)
        with mock.patch.object(loop, "busy_areas", side_effect=busy):
            self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual(self.started, [("x-2", "s1")])
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        self.assertFalse([c for c in bd.calls if c[:1] == ("update",) and c[1:2] == ("x-1",) and "--claim" in c])

    def test_the_loop_marks_its_slot_with_the_bead_it_runs(self):
        bd = self.lanes({"x-1": [rec("landed")]}, {"x-1": "live"})
        seen = {}
        self.during.append(lambda: seen.update(meta=dict(bd.slots["sl-1"].get("metadata") or {}),
                                               lock=tl.read_engine_lock(self.slot("s1"))))
        self.run_loop()
        self.assertEqual(seen["meta"].get("held_bead"), "x-1")
        self.assertEqual(seen["lock"].get("bead"), "x-1")

    def test_when_every_ready_bead_waits_for_its_area_the_loop_waits_instead_of_draining(self):
        bd = self.lanes({"x-1": [], "x-2": [rec("landed")]}, {"x-1": "live", "x-2": "live"})
        self.running(bd, "x-1")

        def nap(secs, *a, **kw):
            self.clock.naps.append(round(secs))
            self.clock.t += secs
            bd.beads["x-1"].update(status="closed", assignee="")  # x-1 ends
            bd.slots["sl-1"].update(status="open", assignee="", metadata={})
        with mock.patch.object(loop, "nap", nap):
            self.assertEqual(self.run_loop(), 0)
        self.assertIn(loop.AREA_POLL, self.clock.naps)
        self.assertEqual([b for b, _ in self.started], ["x-2"])
        self.assertIn("area", self.out)

    def test_a_mark_a_reclaim_left_on_a_slot_bead_is_cleared_by_the_next_take(self):
        """bd reclaim frees a dead loop's slot bead but keeps its metadata: a hold or a loop's take there must not
        leave the old bead running in its area."""
        bd = self.lanes({"x-1": [], "x-2": []}, {"x-1": "live", "x-2": "live"})
        bd.beads["x-1"]["status"] = "closed"
        bd.slots["sl-1"]["metadata"] = {"held_bead": "x-1"}  # open, as reclaim left it
        self.assertEqual(self.cli("slot", "hold", "s1", "--why", "screenshots")[0], 0)
        self.assertEqual(loop.running(str(self.repo)), {})
        self.assertEqual(self.order(), (["x-2"], {}))
        bd.slots["sl-2"]["metadata"] = {"held_bead": "x-1"}
        self.assertEqual(tl.take_slot(str(self.repo), self.cfg_slots())[0], "s2")
        self.assertEqual(loop.running(str(self.repo)), {})

    def cfg_slots(self):
        return tl.profile_slots(str(self.repo))

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
        rc, r, out = self.run_task("x-2", slot="s2", flags={"exclusive_area": True})
        self.assertEqual((rc, r["outcome"]), (1, "taken"))
        self.assertIn("area live busy: x-1 in s1", r["why"])
        self.made.assert_not_called()
        self.assertEqual((bd.slots["sl-2"]["status"], bd.slots["sl-2"]["assignee"]), ("open", ""))
        self.assertFalse(tl.engine_lock_path(self.slot("s2")).exists())

    def test_a_hand_run_in_a_free_area_or_with_no_area_says_nothing(self):
        bd = self.lanes({"x-1": [], "x-2": [], "x-3": []}, {"x-1": "live", "x-2": "shell"})
        self.running(bd, "x-1")
        for b in ("x-2", "x-3"):
            rc, r, out = self.run_task(b, slot="s2", flags={"exclusive_area": True})
            self.assertEqual(r["outcome"], "landed", out)
            self.assertNotIn("area", out)


class Line(Slots):
    """The slot line: tickets under the repo's slot state, served first come first."""

    def setUp(self):
        super().setUp()
        self.cfg = tl.profile_slots(str(self.repo))

    def tickets(self):
        return list(tl.ticket_dir(str(self.repo)).glob("*.json"))

    def waiter(self, label, served, hold=0.05):
        def go():
            got = tl.wait_slot(str(self.repo), self.cfg, label, poll=(0.01, 0.02))
            served.append((label, got[0] if got else None))
            time.sleep(hold)
            tl.release_slot(str(self.repo), got[0])
        th = threading.Thread(target=go, daemon=True)
        th.start()
        return th

    def until(self, cond, secs=5):
        end = time.time() + secs
        while time.time() < end and not cond():
            time.sleep(0.01)
        self.assertTrue(cond())

    def test_three_waiters_on_one_slot_are_served_in_arrival_order(self):
        bd = self.beads({}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        served, threads = [], []
        for n in ("w1", "w2", "w3"):
            threads.append(self.waiter(n, served))
            self.until(lambda: len(self.tickets()) == len(threads))  # w2 arrives after w1 has its ticket
        time.sleep(0.1)
        self.assertEqual(served, [])  # nobody steals the held slot
        tl.release_slot(str(self.repo), "s1")
        for th in threads:
            th.join(10)
        self.assertEqual(served, [("w1", "s1"), ("w2", "s1"), ("w3", "s1")])
        self.assertEqual(self.tickets(), [])

    def test_a_waiter_behind_a_live_ticket_never_takes_a_free_slot_and_a_killed_waiter_does_not_block(self):
        self.beads({}, slots=1)
        k = subprocess.Popen([sys.executable, "-c", "import sys, time; sys.path.insert(0, %r); import tl; "
                              "tl.take_ticket(%r, 'first'); print('in line', flush=True); time.sleep(60)"
                              % (str(HERE), str(self.repo))], stdout=subprocess.PIPE, text=True)
        self.kids.append(k)
        self.assertEqual(k.stdout.readline().strip(), "in line")
        tries = []
        got = tl.wait_slot(str(self.repo), self.cfg, "second", poll=(0.01, 0.01),
                           stop=lambda: tries.append(1) or len(tries) >= 5)
        self.assertIsNone(got)  # the slot is free, but the first in line is alive
        self.assertEqual(len(self.tickets()), 1)  # its own ticket gone, the first one's kept
        k.kill()
        k.wait()
        k.stdout.close()
        got = tl.wait_slot(str(self.repo), self.cfg, "second", poll=(0.01, 0.01), stop=lambda: True)
        self.assertEqual(got[0], "s1")
        self.assertEqual(self.tickets(), [])  # the dead waiter's ticket was dropped

    def test_two_takers_of_one_actor_never_both_win_a_slot(self):
        """bd lets an actor re-claim its own bead, and hand runs of one session share its actor: a `--slot any` that
        listed s1 free must not win it after a hand `--slot s1` took it (race test, seed 3)."""
        bd = self.beads({}, slots=1)
        real_bd = tl.bd

        def bd_13(*a, **kw):  # bd 1.3: a claim by the bead's own assignee succeeds again
            if a[0] == "update" and "--claim" in a and bd.slots.get(a[1], {}).get("assignee") == tl.actor():
                return mock.Mock(returncode=0, stdout="", stderr="")
            return real_bd(*a, **kw)
        won, real_claim = {}, tl.claim_slot

        def claim(repo, bead_id):  # the hand run takes s1 between this taker's look and its claim
            if "thread" in won or threading.current_thread() is not threading.main_thread():
                return real_claim(repo, bead_id)
            th = threading.Thread(target=lambda: won.update(hand=tl.take_named_slot(repo, "s1", self.cfg, "hand")[0]))
            won["thread"] = th
            th.start()
            th.join(0.3)
            return real_claim(repo, bead_id)
        with mock.patch.object(tl, "bd", side_effect=bd_13), mock.patch.object(tl, "claim_slot", side_effect=claim):
            got = tl.take_slot(str(self.repo), self.cfg, "any")
        won["thread"].join(5)
        self.assertEqual(sum(1 for x in (got, won.get("hand")) if x), 1, (got, won))

    def test_tickets_are_numbered_in_arrival_order_and_name_their_waiter(self):
        repo = str(self.repo)
        a, b = tl.take_ticket(repo, "loop"), tl.take_ticket(repo, "run-task x-1")
        self.assertLess(a["seq"], b["seq"])
        line = tl.waiting_line(repo)
        self.assertEqual([t["seq"] for t in line], [a["seq"], b["seq"]])
        self.assertEqual((line[0]["pid"], line[0]["start"], line[1]["why"]), (os.getpid(), tl.proc_start(os.getpid()),
                                                                              "run-task x-1"))
        tl.drop_ticket(a)
        c = tl.take_ticket(repo, "later")
        self.assertGreater(c["seq"], b["seq"])  # a number is never given twice
        for t in (b, c):
            tl.drop_ticket(t)

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
        rc, r, out = self.run_task("x-1", slot="any")
        self.assertEqual((rc, r["outcome"]), (1, "taken"))
        self.assertIn("no free slot", r["why"])
        self.made.assert_not_called()
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-other")
        self.assertEqual(self.tickets(), [])

    def test_run_task_slot_any_wait_gets_the_slot_once_it_frees(self):
        bd = self.beads({"x-1": []}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        threading.Timer(0.2, lambda: bd.slots["sl-1"].update(status="open", assignee="")).start()
        with mock.patch.object(tl, "TICKET_POLL", (0.01, 0.05)):
            rc, r, out = self.run_task("x-1", slot="any", flags={"wait": True})
        self.assertEqual((rc, r["outcome"]), (0, "landed"), out)
        self.assertEqual(self.made.call_args[0][1], str(Path(self.slot("s1")).resolve()))
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))

    def test_the_loop_waits_in_the_line_too(self):
        bd = self.beads({"x-1": [rec("landed")]}, slots=1)
        first = tl.take_ticket(str(self.repo), "a hand run waiting before the loop came")
        naps = []

        def nap(secs, *a, **kw):
            naps.append(secs)
            self.clock.t += secs
            if len(naps) == 3:
                tl.drop_ticket(first)  # served (or gone)
        with mock.patch.object(loop, "nap", nap):
            self.assertEqual(self.run_loop(), 0)
        self.assertGreaterEqual(len(naps), 3)  # the slot was free all along: the loop waited its turn
        self.assertEqual(self.started, [("x-1", "s1")])
        self.assertIn("in line", self.out)


if __name__ == "__main__":
    unittest.main()
