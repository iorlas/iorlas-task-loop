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
from taskloop.contracts.bead import BdError, Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure
from taskloop.contracts.slots import SlotFail, SlotGitError
from taskloop.domain.lanes import pauses


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
        self.assertEqual(verdict.outcome, Result.PAUSED)
        self.assertEqual(pauses.rule(verdict.kind).permanence, "transient")
        self.assertEqual(self.bd.beads[bid].status, "open")
        self.assertEqual(self.bd.beads[bid].assignee, "")
        counters = Counters(slot_quick={"s1": ["previous"]})
        settle, files = self.settle(counters)
        with mock.patch("taskloop.app.loop.settle.verbs.hold") as hold:
            settle.apply(verdict, bid, "s1", True)
        hold.assert_not_called()
        files.rest_bead.assert_not_called()
        self.assertEqual((counters.ran, counters.fails, counters.pauses), (0, [], {}))
        self.assertEqual(counters.slot_quick["s1"], [])
        self.assertEqual(counters.later[bid], self.env.now() + LoopConfig().pause_retry)

    def test_a_reset_that_self_heals_is_not_a_slot_failure(self):
        with mock.patch.object(Slot, "ready_for", side_effect=[SlotFail("slot_broken", "setup failed"), None]) as reset:
            self.assertIsNone(self.taker().prepare("s1", "x-1"))
        self.assertEqual(reset.call_count, 2)

    def test_bd_and_filesystem_failures_are_transient_without_slot_failure_counts(self):
        failures = [BdFailure(BdError(kind="other", text="Dolt unavailable")), OSError("slot directory missing")]
        for failure in failures:
            with self.subTest(failure=failure), mock.patch.object(Slot, "ready_for", side_effect=failure):
                verdict = self.taker().prepare("s1", "x-1")
            assert verdict is not None
            self.assertTrue(verdict.pre_engine)
            self.assertEqual(verdict.outcome, Result.PAUSED)
            self.assertFalse(verdict.quick_slot_failure(LoopConfig().quick_fail_min))

    def test_only_repeated_slot_faults_after_failed_recovery_allow_set_aside(self):
        counters = Counters()
        settle, _files = self.settle(counters)
        with (
            mock.patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")) as reset,
            mock.patch.object(settle, "aside", return_value=True) as aside,
        ):
            for number in range(LoopConfig().slot_fails_to_set_aside):
                verdict = self.taker().prepare("s1", f"x-{number}")
                assert verdict is not None
                settle.apply(verdict, f"x-{number}", "s1", True)
        self.assertEqual(reset.call_count, 2 * LoopConfig().slot_fails_to_set_aside)
        aside.assert_called_once()

    def test_an_engine_slot_failure_with_ready_facts_does_not_count_toward_set_aside(self):
        counters = Counters(slot_quick={"s1": ["previous"]})
        settle, _files = self.settle(counters)
        verdict = vd.Verdict(Result.FAILED, kind="fault_slot", slot_fault="slot_broken", minutes=0.1)
        with mock.patch.object(Slot, "check_ready") as probe:
            self.assertFalse(settle.count_slot(verdict, "x-1", "s1"))
        probe.assert_called_once_with()
        self.assertEqual(counters.slot_quick["s1"], [])

    def test_another_branchs_unsaved_work_counts_even_when_the_slot_cannot_be_held(self):
        counters = Counters()
        settle, _files = self.settle(counters)
        verdict = vd.Verdict(
            Result.FAILED,
            why="failed: worktree /w/.slots/s1 has uncommitted work of another branch",
            kind="fault_slot",
            slot_fault="slot_broken",
            minutes=0.3,
        )
        with mock.patch.object(Slot, "check_ready") as probe, mock.patch("taskloop.app.loop.settle.verbs.hold", return_value=1) as hold:
            for number in range(LoopConfig().slot_fails_to_set_aside):
                self.assertIsNone(settle.apply(verdict, f"x-{number}", "s1", True))
        probe.assert_not_called()  # the verdict already establishes the dirty branch
        hold.assert_called_once()
        self.assertEqual(counters.slot_quick["s1"], [f"x-{LoopConfig().slot_fails_to_set_aside - 1}"])
        self.assertTrue(any("could not be set aside" in line for line in self.out))

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
                self.assertFalse(settle.count_slot(verdict, "x-1", "s1"))
            self.assertEqual(counters.slot_quick["s1"], [])

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
                    self.assertFalse(settle.count_slot(verdict, "x-1", "s1"))
                setup.assert_not_called()
                self.assertEqual(counters.slot_quick["s1"], ["x-1"] if dirty else [])
                self.assertTrue(all(call[0] in ("dirty", "rebasing") for call in self.git.calls))
                self.assertEqual(self.git.tree(self.d1).branch, "task/other")
                self.assertEqual(self.git.tree(self.d1).dirty, dirty)
