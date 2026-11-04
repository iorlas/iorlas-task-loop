"""Resource waits keep the loop alive, claim nothing, and have explicit wake probes."""
from unittest.mock import Mock, patch

import support.paths  # noqa: F401
from slots.test_slot_pool import Rig
from support.fake_loop_env import slot_loop_env

from taskloop.app.loop.env import Storm
from taskloop.app.loop.loop import Loop, LoopArgs
from taskloop.app.loop.queue import Queue, Ranked
from taskloop.app.loop.settle import Settle
from taskloop.app.loop.verdict import Verdict
from taskloop.app.slots import aside
from taskloop.app.slots.pool import Slot
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import SlotFail


class Waits(Rig):
    def make_loop(self):
        env = slot_loop_env(self.env)
        env.profile = RepoProfile
        env.roles = lambda: {}
        env.storm = lambda: None
        files = Mock()
        files.stop_for.return_value = ""
        loop = Loop(env, files, Mock(), LoopArgs())
        loop.nap = Mock(side_effect=lambda seconds, until=0: self.t.__setitem__(0, self.t[0] + seconds))
        return loop

    def test_low_disk_and_ram_wait_without_fetching_or_claiming_then_wake(self):
        for reason in ("low_disk", "low_ram"):
            with self.subTest(reason=reason):
                loop = self.make_loop()
                loop.env.free_bytes = lambda low=reason == "low_disk": 0 if low else 1 << 62
                loop.env.available_mb = lambda low=reason == "low_ram": 0 if low else None
                self.assertIsNone(loop.step())
                assert loop.wait is not None
                self.assertEqual(loop.wait.reason, reason)
                self.assertTrue(loop.wait.wake)
                self.assertFalse(loop.exit)
                self.assertEqual(loop.c.ran, 0)
                loop.env.free_bytes = lambda: 1 << 62
                loop.env.available_mb = lambda: None
                self.assertFalse(loop.resource_wait())
                self.assertIsNone(loop.wait)

    def test_storm_quarantines_one_fingerprint_and_clear_wakes(self):
        loop = self.make_loop()
        loop.env.storm = lambda: Storm("FAULT_INFRA one", "storm")
        self.assertIsNone(loop.step())
        assert loop.wait is not None
        self.assertEqual(loop.wait.fingerprint, "FAULT_INFRA one")
        self.assertFalse(loop.exit)
        loop.env.storm = lambda: None
        self.assertFalse(loop.resource_wait())

    def test_missing_outcomes_wait_for_cooldown_and_stop_still_works(self):
        loop = self.make_loop()
        settle: Settle = loop.settle
        for bid in ("x-1", "x-2"):
            self.assertIsNone(settle.apply(Verdict(Result.FAILED), bid, "", False))
        self.assertTrue(loop.resource_wait())
        assert loop.wait is not None
        self.assertEqual(loop.wait.fingerprint, "missing_outcome")
        self.assertFalse(loop.resource_wait())
        loop.files.stop_for = lambda pid, started: "after"
        self.assertEqual(loop.ends(), 0)
        self.assertEqual(loop.exit["reason"], "stop_request")

    def test_no_lane_wait_publishes_a_role_wake_and_role_recovery_releases_it(self):
        loop = self.make_loop()
        usable = [False]
        loop.env.roles = lambda: {"worker": usable[0]}
        loop.gate.roles = loop.env.roles
        bead = Bead(id=BeadId("x-1"), title="work", status="open")
        loop.gate.hold(bead.id, "worker")
        loop.c.later[bead.id] = 0
        self.assertIsNone(loop.idle(Queue(ranked=[Ranked(bead, "only candidate")])))
        assert loop.wait is not None
        self.assertEqual(loop.wait.reason, "no_lane")
        self.assertEqual(loop.st.wait, loop.wait)
        self.assertFalse(loop.exit)
        usable[0] = True
        self.t[0] = loop.wait.probe_at  # the idle nap lasted a whole role-view cache; the next look sees the recovery
        self.assertTrue(loop.gate.ready(bead.id))
        self.assertNotIn(bead.id, loop.gate.held)
        self.assertFalse(loop.resource_wait())
        self.assertIsNone(loop.wait)

    def block_same_bead(self, loop):
        verdict = Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1,
                          why="failed: worktree /w has uncommitted work of another branch")
        for _ in range(loop.tune().slot_fails_to_set_aside):
            loop.settle.apply(verdict, "x-1", "s1", True)
        self.assertEqual(loop.c.slot_blocked, {"s1": "x-1"})
        self.assertIsNone(self.slot().hold())
        return Bead(id=BeadId("x-1"), title="work", status="open")

    def test_same_bead_waits_for_successful_reset_and_setup_without_clock_hold(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot().take("loop")
        now = self.t[0]
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            self.assertEqual(loop.settle.candidates("s1", [bead]), [])
        self.assertEqual(loop.c.slot_blocked, {"s1": "x-1"})
        self.assertEqual(self.slot().slot_bead().metadata["aside_probe"], "pending")
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup") as setup:
            self.assertEqual(loop.settle.candidates("s1", [bead]), [bead])
        setup.assert_called_once()
        self.assertEqual(loop.c.slot_blocked, {})
        self.assertEqual(self.t[0], now)

    def test_different_eligible_bead_releases_same_bead_condition_without_probe(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        other = Bead(id=BeadId("x-2"), title="other work", status="open")
        with patch.object(aside, "check") as probe:
            self.assertEqual(loop.settle.candidates("s1", [bead, other]), [other])
        probe.assert_not_called()
        self.assertEqual(loop.c.slot_blocked, {})

    def test_taking_another_slot_cannot_bypass_same_bead_condition(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot("s2").take("loop")
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            self.assertEqual(loop.settle.candidates("s2", [bead]), [])
        self.assertEqual(loop.c.slot_blocked, {"s1": "x-1"})
        self.assertEqual(self.slot("s1").slot_bead().status, "open")
