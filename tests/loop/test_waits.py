"""Resource waits keep the loop alive, claim nothing, and have explicit wake probes."""
from unittest.mock import Mock, patch

from support.fake_loop_env import slot_loop_env

from taskloop.app.loop.loop import Loop, LoopArgs
from taskloop.app.loop.verdict import Verdict
from taskloop.app.loop.waits import blocked
from tlkernel.bead import Bead
from tlkernel.config import LoopConfig, RepoProfile
from tlkernel.enums import Result
from tlkernel.ids import BeadId
from tlkernel.slots import SlotFail
from tlslots import aside
from tlslots.pool import Slot
from tlslots.testing import Rig


class Waits(Rig):
    def make_loop(self):
        env = slot_loop_env(self.env)
        env.profile = RepoProfile
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
                start = self.t[0]
                assert loop.step() is None
                assert loop.wait is not None
                assert loop.wait.reason == reason
                assert self.t[0] - start == LoopConfig().wait_poll  # the one nap lasted a whole wait_poll
                assert loop.wait.wake
                assert not loop.exit
                assert loop.c.ran == 0
                loop.env.free_bytes = lambda: 1 << 62
                loop.env.available_mb = lambda: None
                assert not loop.resource_wait()
                assert loop.wait is None

    def test_resource_probe_interval_is_independent_of_child_poll_and_floored(self):
        loop = self.make_loop()
        for reason in ("low_disk", "low_ram"):
            loop.env.free_bytes = lambda low=reason == "low_disk": 0 if low else 1 << 62
            loop.env.available_mb = lambda low=reason == "low_ram": 0 if low else None
            for interval, expected in ((45, 45), (0, 1), (-2, 1)):
                with self.subTest(reason=reason, interval=interval):
                    wait = blocked(loop.env, LoopConfig(poll=7, wait_poll=interval))
                    assert wait is not None
                    assert wait.reason == reason
                    assert wait.probe_at == self.t[0] + expected

    def block_same_bead(self, loop):
        verdict = Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1,
                          why="failed: worktree /w has uncommitted work of another branch")
        for _ in range(loop.tune().slot_fails_to_set_aside):
            loop.settle.apply(verdict, "x-1", "s1", True)
        assert loop.c.slot_blocked == {"s1": "x-1"}
        assert self.slot().hold() is None
        return Bead(id=BeadId("x-1"), title="work", status="open")

    def test_same_bead_waits_for_successful_reset_and_setup_without_clock_hold(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot().take("loop")
        self.t[0] += 31 * 60  # the first probe is due 30 minutes after the set-aside
        now = self.t[0]
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            assert loop.settle.candidates("s1", [bead]) == []
        assert loop.c.slot_blocked == {"s1": "x-1"}
        assert self.slot().slot_bead().metadata["aside_probe"] == "pending"
        self.t[0] += 61 * 60  # and the next one 60 minutes after that failed
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup") as setup:
            assert loop.settle.candidates("s1", [bead]) == [bead]
        setup.assert_called_once()
        assert loop.c.slot_blocked == {}
        assert self.t[0] == now + 61 * 60
        assert not {"aside_level", "aside_probe", "aside_until"} & set(self.slot().slot_bead().metadata)

    def test_a_set_aside_slot_is_probed_after_30_then_60_then_120_minutes_and_120_repeats(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot().take("loop")
        waits = []
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            for failed in range(5):
                start = self.t[0]
                while self.slot().slot_bead().metadata.get("aside_level") != str(failed + 1):
                    self.t[0] += 60  # a minute at a time: the probe runs on the first pass that finds it due
                    assert loop.settle.candidates("s1", [bead]) == []
                waits.append((self.t[0] - start) // 60)
        assert waits == [30, 60, 120, 120, 120]

    def test_no_probe_runs_before_it_is_due(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot().take("loop")
        self.t[0] += 29 * 60
        with patch.object(aside, "setup") as setup:
            assert loop.settle.candidates("s1", [bead]) == []
        setup.assert_not_called()
        assert "aside_probe" not in self.slot().slot_bead().metadata

    def test_different_eligible_bead_releases_same_bead_condition_without_probe(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        other = Bead(id=BeadId("x-2"), title="other work", status="open")
        with patch.object(aside, "check") as probe:
            assert loop.settle.candidates("s1", [bead, other]) == [other]
        probe.assert_not_called()
        assert loop.c.slot_blocked == {}

    def test_taking_another_slot_cannot_bypass_same_bead_condition(self):
        loop = self.make_loop()
        bead = self.block_same_bead(loop)
        self.slot("s2").take("loop")
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            assert loop.settle.candidates("s2", [bead]) == []
        assert loop.c.slot_blocked == {"s1": "x-1"}
        assert self.slot("s1").slot_bead().status == "open"
