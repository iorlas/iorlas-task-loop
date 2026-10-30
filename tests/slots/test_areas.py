"""Areas (tl-bxk.11.4): two concurrent beads never work the same area; the queue skips a bead whose area runs elsewhere.
The slot line (tl-bxk.11.5): waiters for a slot are served in arrival order; a dead waiter never blocks the line."""

import dataclasses
import io
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python3 -m unittest tests.test_areas, from the repo root
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from loop.test_loop import bead

# isort: split
from support import (
    looptest,
    tlbd,
)
from support import slots as sl
from support.builders import cfg_with
from support.fakes import (
    FakeBeadStore,
    as_bead,
)
from support.narrow import must

from slots.test_slots import Slots
from taskloop.adapters import ident
from taskloop.app.loop.queue import QueueRule
from taskloop.app.slots.pool import Slot, SlotPool
from taskloop.app.wire import slots as wslots
from taskloop.contracts import fence
from taskloop.contracts.bead import BdError
from taskloop.contracts.fence import SLOT_GEN
from taskloop.contracts.ports import BdFailure

LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"

HERE = Path(__file__).resolve().parents[2] / "skills" / "task-loop"
AREAS_JSON = {"area_label_prefix": "lane:", "areas": {"core": ["e-core"], "build": ["build"]}}
AREAS = cfg_with(**AREAS_JSON)


def tbead(*a, **k):
    return as_bead(bead(*a, **k))


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


def area_of(b, cfg, cache):
    rule = QueueRule(mock.Mock(), cfg, {}, lambda _: "")
    rule.parents = dict(cache)
    return rule.area_of(b)


class AreaOf(unittest.TestCase):
    def test_the_areas_map_first_then_the_label_prefix_first_match_wins_and_none_is_unrestricted(self):
        cache = {"e-core.1": "e-core", "e-core": None, "e-9": None}
        self.assertEqual(area_of(tbead("x-1", parent="e-core.1", labels=["lane:live"]), AREAS, cache), "core")
        self.assertEqual(area_of(tbead("x-2", labels=["lane:live", "lane:sim"]), AREAS, cache), "live")
        self.assertEqual(area_of(tbead("x-3", labels=["build"]), AREAS, cache), "build")
        self.assertEqual(area_of(tbead("x-4", parent="e-9", labels=["auto"]), AREAS, cache), "")
        self.assertEqual(area_of(tbead("x-5", labels=["lane:live"]), cfg_with(), cache), "")  # no area config: none


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


    def cfg_slots(self):
        return wslots.profile_slots(str(self.repo))


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

    def test_three_waiters_on_one_slot_are_served_in_arrival_order(self):
        bd = self.beads({}, slots=1)
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-other")
        served, threads = [], []
        for n in ("w1", "w2", "w3"):
            threads.append(self.waiter(n, served))
            self.until(lambda: len(self.tickets()) == len(threads))  # w2 arrives after w1 has its ticket
        end = time.monotonic() + 0.3
        while time.monotonic() < end:  # a short watch, polled: nobody steals the held slot
            self.assertEqual(served, [])
            time.sleep(0.01)
        wslots.release_slot(str(self.repo), "s1", force=True)  # tl-other's claim: bd frees another actor's only with --force
        for th in threads:
            th.join(60)
        self.assertEqual(served, [("w1", "s1"), ("w2", "s1"), ("w3", "s1")])
        self.assertEqual(self.tickets(), [])


    @NO_FCNTL
    def test_two_takers_of_one_actor_never_both_win_a_slot(self):
        """bd lets an actor re-claim its own bead, and hand runs of one session share its actor: a `--slot any` that
        listed s1 free must not win it after a hand `--slot s1` took it (race test, seed 3)."""
        bd = self.beads({}, slots=1)
        real_bd = bd

        def bd_13(*a, **kw):  # bd 1.3: a claim by the bead's own assignee succeeds again
            if a[0] == "update" and "--claim" in a and bd.slots.get(a[1], {}).get("assignee") == ident.actor():
                return mock.Mock(returncode=0, stdout="", stderr="")
            return real_bd(*a, **kw)
        won, real_claim = {}, Slot.claimed

        def claim(slot):  # the hand run takes s1 between this taker's look and its claim
            if "thread" in won or threading.current_thread() is not threading.main_thread():
                return real_claim(slot)
            th = threading.Thread(target=lambda: won.update(hand=wslots.take_named_slot(str(self.repo), "s1", self.cfg, "hand")[0]))
            won["thread"] = th
            th.start()
            th.join(0.3)
            return real_claim(slot)
        with tlbd.bd_boundary(bd_13), mock.patch.object(Slot, "claimed", claim):
            got = sl.take_slot(str(self.repo), self.cfg, "any")
        won["thread"].join(60)
        self.assertEqual(sum(1 for x in (got, won.get("hand")) if x), 1, (got, won))

    def test_tickets_are_numbered_in_arrival_order_and_name_their_waiter(self):
        repo = str(self.repo)
        a, b = sl.take_ticket(repo, "loop"), sl.take_ticket(repo, "run-task x-1")
        self.assertLess(a.seq, b.seq)
        line = wslots.waiting_line(repo)
        self.assertEqual([t.seq for t in line], [a.seq, b.seq])
        self.assertEqual((line[0].pid, line[1].why), (os.getpid(), "run-task x-1"))
        sl.drop_ticket(repo, a)
        c = sl.take_ticket(repo, "later")
        self.assertGreater(c.seq, b.seq)  # a number is never given twice
        for t in (b, c):
            sl.drop_ticket(repo, t)

    def test_a_p0_waiter_is_served_before_a_p2_waiter_that_joined_first(self):
        """tl-43k: lifesim's P0 hclf.34 sat 10th in line behind P2 beads."""
        self.beads({}, slots=1)
        repo = str(self.repo)
        p2 = sl.take_ticket(repo, "run-task p2-bead", 2)  # joined first, alive (this process)
        p0 = sl.take_ticket(repo, "run-task p0-bead", 0)
        self.assertLess(p2.seq, p0.seq)
        self.assertEqual([t.why for t in wslots.waiting_line(repo)], ["run-task p0-bead", "run-task p2-bead"])
        sl.drop_ticket(repo, p0)
        got = wslots.wait_slot(repo, self.cfg, "late p0", poll=(0.01, 0.01), stop=lambda: True, prio=0)
        self.assertEqual(must(got)[0], "s1")  # the P0 newcomer passes the P2 waiter that was there first
        wslots.release_slot(repo, "s1")
        self.assertIsNone(
            wslots.wait_slot(repo, self.cfg, "late p3", poll=(0.01, 0.01), stop=lambda: True, prio=3)
        )  # the P2 waiter is ahead
        p0b = sl.take_ticket(repo, "p0 again", 0)
        self.assertIsNone(wslots.wait_slot(repo, self.cfg, "p2 behind p0", poll=(0.01, 0.01), stop=lambda: True, prio=2))  # a P0 is ahead
        for t in (p2, p0b):
            sl.drop_ticket(repo, t)

    def test_a_bead_that_cannot_be_read_waits_as_a_p2(self):
        store = FakeBeadStore()
        for boom in (BdFailure(BdError(kind="other", text="x")), BdFailure(BdError(kind="not_found"))):
            def unreadable(bead, cwd=None, _boom=boom):
                raise _boom
            with store.stub(show_fn=unreadable):
                self.assertEqual(wslots.bead_priority(str(self.repo), "x-1", store), 2)
        with store.stub(show={"priority": 0}):
            self.assertEqual(wslots.bead_priority(str(self.repo), "x-1", store), 0)

    def test_equal_priorities_keep_arrival_order_and_an_unreadable_priority_is_p2(self):
        repo = str(self.repo)
        ts = [sl.take_ticket(repo, "a", 1), sl.take_ticket(repo, "b", 1), sl.take_ticket(repo, "c")]
        self.assertEqual([t.why for t in wslots.waiting_line(repo)], [*["a", "b", "c"][:2], "c"])
        self.assertEqual((wslots.prio_of(tbead("x-1", 0)), wslots.prio_of(tbead("x-1", 1)), wslots.prio_of(None)), (0, 1, 2))
        for t in ts:
            sl.drop_ticket(repo, t)


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(AreasBase):
    """Review of the areas and the slot line: the expired-hold clean-up, release by the holder only, an unreadable
    holder, a ticket without seq, a long area wait, two exclusive hand runs."""

    def expired(self, bd, sb="sl-1"):
        bd.slots[sb].update(status="in_progress", assignee="tl-old", metadata={
            "held_by": "tl-old", "held_since": "2026-10-21T10:00:00", "held_why": "screenshots", "hold_until": "1"})

    @NO_FCNTL
    def test_two_freers_of_one_expired_hold_and_a_taker_never_wipe_the_takers_slot(self):
        bd = self.beads({}, slots=1)
        self.expired(bd)
        repo, cfg = str(self.repo), wslots.profile_slots(str(self.repo))
        real_bd, paused, go, won = bd, threading.Event(), threading.Event(), {}

        def bd_pause(*a, **kw):  # P2 has read the expired hold and stops before it wipes the marks
            if a[0] == "update" and "--unset-metadata" in a and threading.current_thread().name == "P2" \
                    and not paused.is_set():
                paused.set()
                go.wait(60)
            return real_bd(*a, **kw)

        def taker(name):
            env = dataclasses.replace(wslots.slot_env(repo, None, cfg), actor=name)  # each thread is its own session
            won[name] = SlotPool(env).take_any(name, "", None)
        with (
            tlbd.bd_boundary(bd_pause),
            mock.patch.object(ident, "actor", side_effect=lambda: threading.current_thread().name),
        ):  # the fake tracker names the claimer so
            p2 = threading.Thread(target=taker, args=("P2",), name="P2")
            p2.start()
            self.assertTrue(paused.wait(60))
            p1 = threading.Thread(target=taker, args=("P1",), name="P1")
            p1.start()
            p1.join(0.4)  # unfixed: P1 frees the slot and takes it meanwhile; fixed: it waits for P2's lock
            go.set()
            p1.join(60)
            p2.join(60)
        winners = [n for n, v in won.items() if v]
        self.assertEqual(len(winners), 1, won)
        slot = bd.slots["sl-1"]
        self.assertEqual((slot["status"], slot["assignee"], slot["metadata"].get("held_by")),
                         ("in_progress", winners[0], winners[0]))

    def test_a_release_from_a_run_whose_slot_was_retaken_leaves_the_new_holders_slot(self):
        bd = self.beads({}, slots=1)
        repo = str(self.repo)
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-new00000"}):
            self.assertTrue(sl.take_slot(repo, wslots.profile_slots(repo), "loop", bead="x-2"))
        before = json.loads(json.dumps(bd.slots["sl-1"]))
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-old00000"}), mock.patch.object(sys, "stderr", err):
            self.assertTrue(wslots.release_slot(repo, "s1", bead="x-1", mine=True))
        self.assertEqual(bd.slots["sl-1"], before)
        self.assertIn("left alone", err.getvalue())
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-new00000"}):  # the right bead of the right actor
            wslots.release_slot(repo, "s1", bead="x-2", mine=True)
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"].get("metadata")), ("open", {"held_gen": "1"}))  # kept

    def test_a_same_actor_retake_keeps_the_new_holders_slot_when_the_old_run_ends(self):
        """The old run's release compared the actor only: the same actor retaking the slot (a second hand run of one session, a loop
        restarted under its name) lost it to the run that came first. The slot's generation tells the takes apart."""
        bd = self.beads({}, slots=1)
        repo = str(self.repo)
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-same0000"}):
            self.assertTrue(sl.take_slot(repo, wslots.profile_slots(repo), "run x-1", bead="x-1"))
            old = fence.gen_of(wslots.slot_bead(repo, "s1"), SLOT_GEN)
            wslots.release_slot(repo, "s1", bead="x-1", mine=True, gen=old)  # the old run's slot lapsed and was freed
            self.assertTrue(sl.take_slot(repo, wslots.profile_slots(repo), "run x-1 again", bead="x-1"))  # same actor, same bead
            new = fence.gen_of(wslots.slot_bead(repo, "s1"), SLOT_GEN)
            self.assertGreater(new, old)
            before = json.loads(json.dumps(bd.slots["sl-1"]))
            err = io.StringIO()
            with mock.patch.object(sys, "stderr", err):
                self.assertTrue(wslots.release_slot(repo, "s1", bead="x-1", mine=True, gen=old))  # the old run ends late
            self.assertEqual(bd.slots["sl-1"], before)
            self.assertIn("left alone", err.getvalue())
            wslots.release_slot(repo, "s1", bead="x-1", mine=True, gen=new)
        self.assertEqual(bd.slots["sl-1"]["status"], "open")


    def test_a_ticket_without_seq_does_not_break_the_line_and_stale_tmp_files_are_swept(self):
        self.beads({}, slots=1)
        repo = str(self.repo)
        d = sl.ticket_dir(repo)
        (d / (f"{7:06d}.json")).write_text(json.dumps({"pid": os.getpid()}))  # no seq, no why: not a ticket
        old, fresh = d / ".1.2.tmp", d / ".1.3.tmp"
        old.write_text("{")
        fresh.write_text("{")
        os.utime(old, (time.time() - 700, time.time() - 700))
        self.assertEqual(wslots.waiting_line(repo), [])
        self.assertIsNotNone(
            wslots.wait_slot(repo, wslots.profile_slots(repo), "x", stop=lambda: True)
        )  # nobody is ahead: the free slot is taken
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())


