"""Infrastructure cannot burn a bead or quarantine a slot before recovery has been attempted."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from slots.test_slot_pool import ME, Rig
from support.fake_loop_env import slot_loop_env

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.settle import Counters, Settle
from taskloop.app.loop.take import Taker
from taskloop.app.slots.pool import Slot
from taskloop.domain.lanes import pauses
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure
from tlkernel.config import LoopConfig
from tlkernel.enums import Result
from tlkernel.ids import BeadId
from tlkernel.slots import SlotFail, SlotGitError


class Infrastructure(Rig):
    def taker(self):
        env = slot_loop_env(self.env)
        return Taker(env, mock.Mock(), LoopConfig, self.out.append, mock.Mock(), {})

    def settle(self, counters):
        files = mock.Mock()
        result = Settle(self.taker().env, files, LoopConfig, self.out.append, counters, mock.Mock(), mock.Mock(), mock.Mock())
        return result, files

    def test_infrastructure_before_engine_requeues_without_failure_rest_or_slot_hold(self):
        bid = BeadId("x-1")
        self.bd.beads[bid] = Bead(id=bid, title="work", status="in_progress", assignee=ME)
        with mock.patch.object(Slot, "ready_for", side_effect=SlotGitError("git/dolt/network unavailable")):
            verdict = self.taker().prepare("s1", bid)
        assert verdict is not None
        assert verdict.outcome == Result.PAUSED
        assert pauses.rule(verdict.kind).permanence == "transient"
        assert self.bd.beads[bid].status == "open"
        assert self.bd.beads[bid].assignee == ""
        counters = Counters(slot_quick={"s1": ["previous"]})
        settle, files = self.settle(counters)
        with mock.patch.object(settle, "aside") as hold:
            settle.apply(verdict, bid, "s1", True)
        hold.assert_not_called()
        files.rest_bead.assert_not_called()
        assert (counters.ran, counters.fails, counters.pauses) == (0, [], {})
        assert counters.slot_quick["s1"] == []
        assert counters.later[bid] == self.env.now() + LoopConfig().pause_retry

    def test_a_reset_that_self_heals_is_not_a_slot_failure(self):
        with mock.patch.object(Slot, "ready_for", side_effect=[SlotFail("slot_broken", "setup failed"), None]) as reset:
            assert self.taker().prepare("s1", "x-1") is None
        assert reset.call_count == 2

    def test_bd_and_filesystem_failures_are_transient_without_slot_failure_counts(self):
        failures = [BdFailure(BdError(kind="other", text="Dolt unavailable")), OSError("slot directory missing")]
        for failure in failures:
            with self.subTest(failure=failure), mock.patch.object(Slot, "ready_for", side_effect=failure):
                verdict = self.taker().prepare("s1", "x-1")
            assert verdict is not None
            assert verdict.pre_engine
            assert verdict.outcome == Result.PAUSED
            assert not verdict.quick_slot_failure(LoopConfig().quick_fail_min)

    def test_only_repeated_slot_faults_after_failed_recovery_allow_set_aside(self):
        counters = Counters()
        settle, _files = self.settle(counters)
        with (
            mock.patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")) as reset,
            mock.patch.object(settle, "aside", return_value=True) as aside,
        ):
            for _ in range(LoopConfig().slot_fails_to_set_aside):
                verdict = self.taker().prepare("s1", "x-1")
                assert verdict is not None
                settle.apply(verdict, "x-1", "s1", True)
        assert reset.call_count == 2 * LoopConfig().slot_fails_to_set_aside
        aside.assert_called_once()

    def test_an_engine_slot_failure_with_ready_facts_does_not_count_toward_set_aside(self):
        counters = Counters(slot_quick={"s1": ["previous"]})
        settle, _files = self.settle(counters)
        verdict = vd.Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1)
        with mock.patch.object(Slot, "check_ready") as probe:
            assert not settle.count_slot(verdict, "x-1", "s1")
        probe.assert_called_once_with()
        assert counters.slot_quick["s1"] == []

    def test_different_beads_do_not_accumulate_slot_failures(self):
        counters = Counters()
        settle, _files = self.settle(counters)
        verdict = vd.Verdict(
            Result.FAILED,
            why="failed: worktree /w/.slots/s1 has uncommitted work of another branch",
            kind="fault_slot",
            slot_fault="slot_broken",
            minutes=0.3,
        )
        with mock.patch.object(Slot, "check_ready") as probe, mock.patch.object(settle, "aside") as hold:
            for number in range(LoopConfig().slot_fails_to_set_aside):
                assert settle.apply(verdict, f"x-{number}", "s1", True) is None
        probe.assert_not_called()  # the verdict already establishes the dirty branch
        hold.assert_not_called()
        assert counters.slot_quick["s1"] == [f"x-{LoopConfig().slot_fails_to_set_aside - 1}"]
        assert counters.slot_blocked == {}

    def test_infrastructure_during_engine_slot_recovery_does_not_count_toward_set_aside(self):
        verdict = vd.Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1)
        failures = [
            SlotFail("transient", "git/dolt/network unavailable"),
            SlotGitError("git unavailable"),
            BdFailure(BdError(kind="other", text="Dolt unavailable")),
            FileNotFoundError("slot directory missing"),
        ]
        for failure in failures:
            counters = Counters(slot_quick={"s1": ["previous"]})
            settle, _files = self.settle(counters)
            with self.subTest(failure=failure), mock.patch.object(Slot, "check_ready", side_effect=failure):
                assert not settle.count_slot(verdict, "x-1", "s1")
            assert counters.slot_quick["s1"] == []

    def test_settle_probe_only_reads_git_even_when_leftover_work_exists(self):
        for dirty in (False, True):
            with self.subTest(dirty=dirty):
                self.git.calls.clear()
                self.git.tree(self.d1).dirty = dirty
                self.git.tree(self.d1).branch = "task/other"
                counters = Counters()
                settle, _files = self.settle(counters)
                verdict = vd.Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1)
                with mock.patch("taskloop.app.slots.reset.setup") as setup:
                    assert not settle.count_slot(verdict, "x-1", "s1")
                setup.assert_not_called()
                assert counters.slot_quick["s1"] == (["x-1"] if dirty else [])
                assert all(call[0] in ("dirty", "rebasing") for call in self.git.calls)
                assert self.git.tree(self.d1).branch == "task/other"
                assert self.git.tree(self.d1).dirty == dirty


class SetupOwnTree(Rig):
    """tl-bxk.10.33.11: a setup that fails with the bead's tree and passes on the base is the bead's, not an infrastructure wait."""

    def test_setup_failing_only_with_the_beads_tree_parks_the_bead_and_leaves_the_slot_clean(self):
        bid = BeadId("x-1")
        self.bd.beads[bid] = Bead(id=bid, title="work", status="in_progress", assignee=ME)
        taker = Taker(slot_loop_env(self.env), mock.Mock(), LoopConfig, self.out.append, mock.Mock(), {})
        broken = SlotFail("slot_broken", "setup exited 1", setup=True)
        with mock.patch.object(Slot, "ready_for", side_effect=[broken, broken, None]) as reset, \
                mock.patch("taskloop.app.loop.stages.setup") as base_setup:
            verdict = taker.prepare("s1", bid)
        assert verdict is not None
        assert (verdict.outcome, verdict.kind, verdict.pre_engine) == (Result.PAUSED, vd.SETUP_OWN_TREE, False)
        assert reset.call_args_list[-1] == mock.call("")
        base_setup.assert_called_once()
        assert self.bd.beads[bid].status == "open"

    def test_setup_failing_on_the_base_too_stays_a_slot_failure(self):
        bid = BeadId("x-1")
        self.bd.beads[bid] = Bead(id=bid, title="work", status="in_progress", assignee=ME)
        taker = Taker(slot_loop_env(self.env), mock.Mock(), LoopConfig, self.out.append, mock.Mock(), {})
        broken = SlotFail("slot_broken", "setup exited 1", setup=True)
        with mock.patch.object(Slot, "ready_for", side_effect=[broken, broken, None]), \
                mock.patch("taskloop.app.loop.stages.setup", side_effect=broken):
            verdict = taker.prepare("s1", bid)
        assert verdict is not None
        assert verdict.pre_engine
        assert verdict.recovery_failed
