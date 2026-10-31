"""STAGERUN: stage-only calls reuse the engine operations and recorded run lifecycle."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl_main

from taskloop.app.land.gate import Gate, Problem, ProblemKind
from taskloop.app.run.blocked import Blocked
from taskloop.app.run.stages import parse_step, round_step, run_stages
from taskloop.app.run.steps import Steps
from taskloop.app.write.state import ACCEPT, StageState
from taskloop.contracts import log as rec
from taskloop.contracts.bead import Bead
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.enums import Step
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunManifest, RunState
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class SelectedStage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        who = Identity(actor="owner", session="stage-session", home=str(Path(tmp.name) / "config"))
        self.locator = RunLocator(who.config)
        self.e = e = mock.Mock()
        e.who, e.home, e.bead, e.wt = who, who.config, BeadId("t-1"), str(self.repo)
        e.stores = fake_stores()
        e.git.common_dir.return_value = ""
        e.git.rev_parse.return_value = "head"
        e.env.bead.return_value = None
        e.claim, e.fresh, e.moved = None, False, False
        e.landed_sha = ""
        e.Blocked, e.kind, e.why = Blocked, Kind.FAULT_ENGINE, ""
        e.plan_data = None
        e.checkpoints.read.return_value = None
        e.store.show.return_value = Bead(id=e.bead, title="stage task", status="open")
        e.lander.gate.green.return_value = False
        e.lander.gate.run.return_value = object()

    def manifest(self) -> RunManifest:
        bundle = self.locator.get(self.e.run_id)
        assert bundle is not None
        return bundle.manifest

    def open_run(self):
        e = self.e
        bundle = self.locator.create(str(self.repo), e.bead, 100)
        e.run_id, e.run_dir = bundle.run, bundle.dir
        e.log = RunLog(e.stores.run_log(bundle.run), run_id=bundle.run)
        e.steps = Steps(e.log, lambda: 100.0)

        def start():
            m = self.manifest()
            e.log.emit(rec.RunStart(worktree=e.wt, mode=m.mode, owner=m.owner, session=m.session))

        e.records.log_run.side_effect = start
        return bundle

    def invoke(self, stage=None):
        self.open_run()
        with mock.patch("taskloop.app.run.stages.Lease"):
            rc = run_stages(self.e, stage, continuous=False)
        return rc, self.manifest()

    def test_gate_runs_only_gate_and_keeps_identified_terminal_manifest(self):
        rc, manifest = self.invoke("gate")
        self.assertEqual(rc, 0)
        self.e.lander.gate.run.assert_called_once_with()
        self.e.lander.finish.assert_not_called()
        self.e.tree.reset.assert_not_called()
        self.e.planner.plan.assert_not_called()
        self.e.closer.close.assert_not_called()
        self.assertEqual((manifest.mode, manifest.owner, manifest.session), ("stage:gate", "owner", "stage-session"))
        self.assertEqual((manifest.state, manifest.next_step), (RunState.DONE, Step.LAND))
        self.e.checkpoints.save.assert_called_once_with(step=Step.LAND, stage=0)

    def test_land_without_green_gate_is_refused_with_reason(self):
        rc, manifest = self.invoke("land")
        self.assertEqual(rc, 1)
        self.assertEqual(manifest.state, RunState.FAILED)
        self.assertIn("no green gate for the current tree and base", manifest.reason)
        self.e.lander.finish.assert_not_called()
        self.e.lander.gate.run.assert_not_called()

    def test_auto_next_uses_checkpoint_stage_and_mode(self):
        self.e.checkpoints.read.return_value = Checkpoint(bead="t-1", run="old", t=1, step="gate")
        rc, manifest = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(manifest.mode, "auto-next")
        self.e.lander.gate.run.assert_called_once_with()
        self.e.tree.reset.assert_not_called()

    def test_auto_next_uses_last_completed_manifest_when_checkpoint_is_absent(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.advance(previous.run, Step.GATE)
        self.locator.end(previous.run, 2, RunState.DONE)
        rc, manifest = self.invoke()
        self.assertEqual((rc, manifest.mode), (0, "auto-next"))
        self.e.lander.gate.run.assert_called_once_with()

    def test_failed_manifest_cursor_wins_over_an_older_checkpoint(self):
        self.e.checkpoints.read.return_value = Checkpoint(bead="t-1", run="old", t=1, step="write")
        previous = self.locator.create(str(self.repo), "t-1", 2)
        self.locator.advance(previous.run, Step.GATE)
        self.locator.end(previous.run, 3, RunState.FAILED, "gate failed")
        self.assertEqual(self.invoke()[0], 0)
        self.e.lander.gate.run.assert_called_once_with()

    def test_explicit_stage_can_rerun_after_a_completed_run(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.end(previous.run, 2, RunState.DONE)
        self.assertEqual(self.invoke("gate")[0], 0)

    def test_live_previous_run_refuses_auto_next(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.beat(previous.run, 2)
        rc, manifest = self.invoke()
        self.assertEqual(rc, 1)
        self.assertIn("still running", manifest.reason)
        self.e.lander.gate.run.assert_not_called()

    def test_close_without_land_is_refused(self):
        rc, manifest = self.invoke("close")
        self.assertEqual(rc, 1)
        self.assertIn("no land on record", manifest.reason)
        self.e.closer.close.assert_not_called()

    def test_red_gate_preserves_reason_and_does_not_advance(self):
        self.e.lander.gate.run.return_value = Problem(ProblemKind.GATE, "gate steps red: mac")
        rc, manifest = self.invoke("gate")
        self.assertEqual((rc, manifest.state, manifest.next_step), (1, RunState.FAILED, Step.GATE))
        self.assertIn("gate steps red: mac", manifest.reason)
        self.e.checkpoints.save.assert_not_called()

    def test_exception_still_seals_manifest(self):
        self.e.lander.gate.run.side_effect = RuntimeError("runner failed")
        with self.assertRaisesRegex(RuntimeError, "runner failed"):
            self.invoke("gate")
        manifest = self.manifest()
        self.assertEqual(manifest.state, RunState.FAILED)
        self.assertIn("runner failed", manifest.reason)

    def test_typed_network_pause_keeps_the_loop_terminal_state(self):
        self.e.lander.gate.run.side_effect = Blocked("network unavailable", kind=Kind.PAUSE_NETWORK)
        rc, manifest = self.invoke("gate")
        self.assertEqual((rc, manifest.state), (1, RunState.STOPPED))
        self.assertEqual(manifest.reason, "network unavailable")

    def test_unknown_stage_lists_every_engine_step(self):
        with self.assertRaises(ValueError) as caught:
            parse_step("mac-gate")
        for step in Step:
            self.assertIn(step.value, str(caught.exception))
        result = tl_main("run-task", "t-1", "--stage", "mac-gate", cwd=self.repo)
        self.assertNotEqual(result.returncode, 0)
        for step in Step:
            self.assertIn(step.value, result.stderr)

    def test_single_stage_cursor_stops_before_another_step_begins(self):
        self.open_run()
        self.e.steps.only = Step.GATE
        self.e.steps.begin("gate", "gate")
        with self.assertRaisesRegex(ValueError, "stopped before land"):
            self.e.steps.begin("land", "land")
        self.assertEqual(self.e.steps.cur.step, "gate")

    def test_land_cannot_rerun_a_gate_that_went_stale(self):
        self.open_run()
        self.e.steps.only = Step.LAND
        self.e.checker.gate_green.return_value = False
        with self.assertRaisesRegex(ValueError, "no longer green"):
            Gate(self.e).run()
        self.e.checker.run_items.assert_not_called()

    def test_loop_uses_same_lifecycle_and_retains_continuous_execution(self):
        self.open_run()
        with mock.patch("taskloop.app.run.stages.RunOnce") as once:
            once.return_value.go.return_value = 0
            self.assertEqual(run_stages(self.e, None, continuous=True), 0)
        once.return_value.go.assert_called_once_with()
        self.assertEqual(self.manifest().mode, "loop")
        self.e.lander.gate.run.assert_not_called()

    def test_separate_round_steps_keep_writer_and_check_evidence_then_reset_counters(self):
        self.open_run()
        e = self.e
        e.plan_data = {"summary": "plan", "stages": [{"goal": "implement", "checks": [], "files": []}]}
        e.stats, e.accepted, e.done, e.last_run = {"writes": 0}, [], [], None
        e.stage_loop.begin.side_effect = StageState
        e.judge.look_step.return_value = ""
        e.stage_loop.reviewing.run.return_value = ACCEPT

        def write(s, **kwargs):
            self.assertFalse(kwargs["look"])
            s.w = {"summary": "written", "checks_run": [], "question": "", "options": [], "decided": "",
                   "bad_checks": [], "new_cases": [], "unchecked": []}
            s.wfam = e.writer_family = "openai"
            return ""

        def checks(s):
            self.assertEqual(s.w["summary"], "written")
            s.run = e.last_run = CheckRun(round=1)
            return ""

        e.stage_loop.writing.run.side_effect = write
        e.stage_loop.checking.run.side_effect = checks
        ck = None
        for step, following in ((Step.WRITE, Step.LOOK), (Step.LOOK, Step.CHECKS),
                                (Step.CHECKS, Step.REVIEW), (Step.REVIEW, Step.VERIFY)):
            self.assertEqual(round_step(e, step, ck), following)
            saved = e.checkpoints.save.call_args.kwargs
            ck = Checkpoint(bead="t-1", run=e.run_id, t=1, **saved)
            if following is not Step.VERIFY:
                assert ck.progress is not None
                assert ck.progress.write is not None
                self.assertEqual((ck.n, ck.progress.write.summary), (1, "written"))
        assert ck is not None
        self.assertEqual((ck.stage, ck.n, ck.rounds, ck.progress), (1, 0, 0, None))
        self.assertEqual(e.accepted, [0])
        e.stage_loop.writing.run.assert_called_once()
        e.stage_loop.checking.run.assert_called_once()
        e.stage_loop.reviewing.run.assert_called_once()
