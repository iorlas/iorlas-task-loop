"""STAGERUN: stage-only calls reuse the engine operations and recorded run lifecycle."""

import sys
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.memstores import fake_stores
from support.tlmain import tl_main

from taskloop.app.land.gate import Gate, Problem, ProblemKind
from taskloop.app.run.stages import run_stages
from taskloop.stores.runlog import RunLog
from tlkernel import closeeffects as effects
from tlkernel import log as rec
from tlkernel import runoutcome as oc
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint
from tlkernel.checks import CheckRun
from tlkernel.enums import Outcome, Result, Step
from tlkernel.finish import finish_run
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.parks import Park, ParkStore
from tlkernel.run import RunManifest, RunState
from tlpipeline.api import Blocked, RecordRun, Steps, answer, parse_step
from tltestkit.checks import typed
from tltestkit.plans import PLAN
from tlwork.plan.keep import PlanKeeper
from tlwork.plan.planned import Planned
from tlwork.write.rounds import round_step
from tlwork.write.state import ACCEPT, StageState


class SelectedStage(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        who = Identity(actor="owner", session="stage-session", home=str(Path(tmp.name) / "config"))
        self.locator = RunLocator(who.config)
        self.e = e = mock.Mock()
        e.cfg.prepare = None
        e.fenced = ""
        e.who, e.home, e.bead, e.wt = who, who.config, BeadId("t-1"), str(self.repo)
        e.stores = fake_stores()
        e.git.common_dir.return_value = ""
        e.git.rev_parse.return_value = "head"
        e.env.bead.return_value = None
        e.claim, e.fresh, e.moved = None, False, False
        e.dry = False
        e.retry_after = 0.0
        e.pause_reason = ""
        e.writer_family, e.replan_first = None, False
        e.landed_sha = ""
        e.Blocked, e.kind, e.why = Blocked, Kind.FAULT_ENGINE, ""
        e.plan_data = None
        data = typed(PLAN)
        e.planner.plan.return_value = Planned(plan_data=data, summary=data["summary"], planned=1)
        e.planner.take.side_effect = lambda p: PlanKeeper(e, e.leftover_sink).take(p)
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
        with mock.patch("taskloop.app.run.run_once.Lease"):
            rc = run_stages(self.e, stage, continuous=False)
        return rc, self.manifest()

    def test_gate_runs_only_gate_and_keeps_identified_terminal_manifest(self):
        rc, manifest = self.invoke("gate")
        assert rc == 0
        self.e.lander.gate.run.assert_called_once_with()
        self.e.lander.finish.assert_not_called()
        self.e.tree.reset.assert_not_called()
        self.e.planner.plan.assert_not_called()
        self.e.closer.close.assert_not_called()
        assert (manifest.mode, manifest.owner, manifest.session) == ("stage:gate", "owner", "stage-session")
        assert (manifest.state, manifest.next_step) == (RunState.DONE, Step.LAND)
        self.e.checkpoints.save.assert_called_once_with(step=Step.LAND, stage=0)
        closes = [row.rec for row in self.e.stores.run_log(self.e.run_id).read_from(0).items if isinstance(row.rec, rec.Close)]
        assert [row.retry_at for row in closes] == [0.0]

    def test_standalone_plan_stores_the_planned_result(self):
        p = self.e.planner.plan.return_value
        rc, manifest = self.invoke("plan")
        assert rc == 0
        assert manifest.next_step is Step.WRITE
        self.e.planner.take.assert_called_once_with(p)
        assert self.e.plan_data is p.plan_data
        assert (self.e.plan_summary, self.e.planned) == (p.summary, p.planned)

    def test_standalone_empty_plan_files_its_owner_ask(self):
        self.e.planner.plan.side_effect = Blocked("noop: no work", kind=Kind.NOOP)
        rc, manifest = self.invoke("plan")
        assert (rc, manifest.state) == (1, RunState.PARKED)
        self.e.closer.apply.assert_called_once()
        effect, done, stats = self.e.closer.apply.call_args.args
        assert (effect, done.kind, stats) == (effects.RaiseAsk(), Kind.NOOP, "")

    def test_land_without_green_gate_is_refused_with_reason(self):
        rc, manifest = self.invoke("land")
        assert rc == 1
        assert manifest.state == RunState.STOPPED
        assert "no green gate for the current tree and base" in manifest.reason
        self.e.lander.finish.assert_not_called()
        self.e.lander.gate.run.assert_not_called()

    def test_auto_next_uses_checkpoint_stage_and_mode(self):
        self.e.checkpoints.read.return_value = Checkpoint(bead="t-1", run="old", t=1, step="gate")
        rc, manifest = self.invoke()
        assert rc == 0
        assert manifest.mode == "auto-next"
        self.e.lander.gate.run.assert_called_once_with()
        self.e.tree.reset.assert_not_called()

    def test_auto_next_uses_last_completed_manifest_when_checkpoint_is_absent(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.advance(previous.run, Step.GATE)
        self.locator.end(previous.run, 2, RunState.DONE)
        rc, manifest = self.invoke()
        assert (rc, manifest.mode) == (0, "auto-next")
        self.e.lander.gate.run.assert_called_once_with()

    def test_failed_manifest_cursor_wins_over_an_older_checkpoint(self):
        self.e.checkpoints.read.return_value = Checkpoint(bead="t-1", run="old", t=1, step="write")
        previous = self.locator.create(str(self.repo), "t-1", 2)
        self.locator.advance(previous.run, Step.GATE)
        self.locator.end(previous.run, 3, RunState.FAILED, "gate failed")
        assert self.invoke()[0] == 0
        self.e.lander.gate.run.assert_called_once_with()

    def test_explicit_stage_can_rerun_after_a_completed_run(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.end(previous.run, 2, RunState.DONE)
        assert self.invoke("gate")[0] == 0

    def test_live_previous_run_refuses_auto_next(self):
        previous = self.locator.create(str(self.repo), "t-1", 1)
        self.locator.beat(previous.run, 2)
        rc, manifest = self.invoke()
        assert rc == 1
        assert "still running" in manifest.reason
        self.e.lander.gate.run.assert_not_called()

    def test_a_reset_stage_is_a_stage_not_a_landed_bead(self):
        rc, manifest = self.invoke("reset")
        assert rc == 0
        assert manifest.next_step is Step.PLAN
        finish = manifest.finish
        assert finish is not None
        assert (finish.outcome, finish.result, finish.kind) == (Outcome.STAGED, Result.STAGED, "stage")
        self.e.checkpoints.keep_end.assert_not_called()  # no close outcome in the checkpoint: the next run is not a "close"

    def test_only_a_land_or_a_close_can_finish_as_landed_or_done(self):
        for stage in ("reset", "plan", "replan", "gate"):
            _, manifest = self.invoke(stage)
            assert manifest.finish is not None
            assert manifest.finish.outcome not in (Outcome.LANDED, Outcome.DONE), stage

    def test_a_stages_answer_keeps_no_close_outcome_for_the_checkpoint(self):
        staged = answer(oc.make(Kind.STAGE), 1.0)
        assert (staged.outcome, staged.result, staged.state, staged.end) == (Outcome.STAGED, Result.STAGED, RunState.DONE, "")
        assert answer(oc.make(Kind.DONE), 1.0).end  # a bead's close still keeps one

    def test_close_without_land_is_refused(self):
        rc, manifest = self.invoke("close")
        assert rc == 1
        assert "no land on record" in manifest.reason
        self.e.closer.close.assert_not_called()

    def test_red_gate_preserves_reason_and_does_not_advance(self):
        self.e.lander.gate.run.return_value = Problem(ProblemKind.GATE, "gate steps red: mac")
        rc, manifest = self.invoke("gate")
        assert (rc, manifest.state, manifest.next_step) == (1, RunState.FAILED, Step.GATE)
        assert "gate steps red: mac" in manifest.reason
        self.e.checkpoints.save.assert_not_called()

    def test_exception_still_seals_manifest(self):
        self.e.lander.gate.run.side_effect = RuntimeError("runner failed")
        with pytest.raises(RuntimeError, match="runner failed"):
            self.invoke("gate")
        manifest = self.manifest()
        assert manifest.state == RunState.FAILED
        assert "runner failed" in manifest.reason

    def test_land_crash_parks_and_auto_next_retries_land(self):
        e = self.e
        e.checkpoints.read.return_value = Checkpoint(bead="t-1", run="old", t=1, step="land")
        e.lander.gate.green.return_value = True
        e.lander.finish.side_effect = KeyError("stale")
        rc, manifest = self.invoke("land")
        assert (rc, manifest.state, manifest.next_step) == (1, RunState.PARKED, Step.LAND)
        assert e.kind.value == "engine_crash"
        assert e.why == "land crashed: KeyError: 'stale'"
        e.checkpoints.drop.assert_not_called()
        e.checkpoints.drop_unless_fenced.assert_not_called()
        e.checkpoints.save.assert_not_called()
        e.lander.finish.side_effect = None
        e.lander.finish.return_value = "landed-sha"
        rc, manifest = self.invoke()
        assert (rc, manifest.next_step) == (0, Step.CLOSE)

    def test_interrupt_at_land_propagates(self):
        self.e.lander.gate.green.return_value = True
        self.e.lander.finish.side_effect = KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            self.invoke("land")
        assert self.e.kind == Kind.FAULT_ENGINE

    def test_land_without_a_recorded_sha_parks_and_keeps_its_cursor(self):
        self.e.lander.gate.green.return_value = True
        self.e.lander.finish.return_value = ""
        rc, manifest = self.invoke("land")
        assert (rc, manifest.state, manifest.next_step) == (1, RunState.STOPPED, Step.LAND)
        assert (self.e.kind, self.e.pause_reason) == (Kind.PAUSE_LANE, "stage_refused")
        assert "no land was recorded" in manifest.reason
        self.e.checkpoints.drop.assert_not_called()
        self.e.checkpoints.drop_unless_fenced.assert_not_called()

    def test_stale_gate_refusal_is_an_owner_pause_without_crash_wording(self):
        self.e.lander.gate.green.return_value = True
        self.e.lander.finish.side_effect = ValueError("land refused: gate is no longer green for this tree and base")
        rc, manifest = self.invoke("land")
        assert (rc, manifest.state) == (1, RunState.STOPPED)
        assert (self.e.kind, self.e.pause_reason) == (Kind.PAUSE_LANE, "stage_refused")
        assert "crash" not in manifest.reason

    def test_typed_network_pause_keeps_the_loop_terminal_state(self):
        self.e.lander.gate.run.side_effect = Blocked("network unavailable", kind=Kind.PAUSE_NETWORK)
        rc, manifest = self.invoke("gate")
        assert (rc, manifest.state) == (1, RunState.STOPPED)
        assert manifest.reason == "network unavailable"

    def test_pause_close_records_the_durable_wake(self):
        e = self.e
        e.retry_after = 999.0
        e.lander.gate.run.side_effect = Blocked("network unavailable", kind=Kind.PAUSE_NETWORK)

        def pause(done):
            ParkStore(e.home).put(
                Park(bead=e.bead, hash="", runs=0, run=e.run_id, t=100.0, reason=done.kind.value, permanence="transient", retry_at=160.0)
            )

        e.closer.pause.side_effect = pause

        def finish(done, stats="", record=None):
            record = record or RecordRun(e).stage  # the engine's real writer, over this test's stand-in engine
            finish_run(e.home, e.run_id, answer(done, 200.0), lambda m, r: record(r, stats))
            return done

        e.records.finish.side_effect = finish
        rc, manifest = self.invoke("gate")
        assert (rc, manifest.state) == (1, RunState.STOPPED)
        closes = [row.rec for row in e.stores.run_log(e.run_id).read_from(0).items if isinstance(row.rec, rec.Close)]
        assert [row.retry_at for row in closes] == [160.0]

    def test_pause_close_ignores_an_older_runs_wake(self):
        e = self.e
        ParkStore(e.home).put(Park(bead=e.bead, hash="", runs=0, run="old", t=100.0, retry_at=160.0))
        e.lander.gate.run.side_effect = Blocked("network unavailable", kind=Kind.PAUSE_NETWORK)
        rc, manifest = self.invoke("gate")
        assert (rc, manifest.state) == (1, RunState.STOPPED)
        closes = [row.rec for row in e.stores.run_log(e.run_id).read_from(0).items if isinstance(row.rec, rec.Close)]
        assert [row.retry_at for row in closes] == [0.0]

    def test_unknown_stage_lists_every_engine_step(self):
        with pytest.raises(ValueError) as caught:
            parse_step("mac-gate")
        for step in Step:
            assert step.value in str(caught.value)
        result = tl_main("run-task", "t-1", "--stage", "mac-gate", cwd=self.repo)
        assert result.returncode != 0
        for step in Step:
            assert step.value in result.stderr

    def test_single_stage_cursor_stops_before_another_step_begins(self):
        self.open_run()
        self.e.steps.only = Step.GATE
        self.e.steps.begin("gate", "gate")
        with pytest.raises(ValueError, match="stopped before land"):
            self.e.steps.begin("land", "land")
        assert self.e.steps.cur.step == "gate"

    def test_land_cannot_rerun_a_gate_that_went_stale(self):
        self.open_run()
        self.e.steps.only = Step.LAND
        self.e.checker.gate_green.return_value = False
        with pytest.raises(ValueError, match="no longer green"):
            Gate(self.e).run()
        self.e.checker.run_items.assert_not_called()

    def test_loop_uses_same_lifecycle_and_retains_continuous_execution(self):
        self.open_run()
        with mock.patch("taskloop.app.run.stages.RunOnce") as once:
            once.return_value.go.return_value = 0
            assert run_stages(self.e, None, continuous=True) == 0
        once.return_value.go.assert_called_once_with()
        assert self.manifest().mode == "loop"
        self.e.lander.gate.run.assert_not_called()

    def test_separate_round_steps_keep_writer_and_check_evidence_then_reset_counters(self):
        self.open_run()
        e = self.e
        e.plan_data = {"summary": "plan", "stages": [{"goal": "implement", "checks": [], "files": []}]}
        e.stats, e.accepted, e.done, e.last_run = {"writes": 0}, [], [], None
        e.stage_loop.begin.side_effect = StageState
        e.judge.look_step.return_value = ""
        e.stage_loop.review.return_value = ACCEPT

        def write(s, **kwargs):
            assert not kwargs["look"]
            s.w = {
                "summary": "written",
                "checks_run": [],
                "question": "",
                "options": [],
                "decided": "",
                "bad_checks": [],
                "new_cases": [],
                "unchecked": [],
            }
            s.wfam = e.writer_family = "openai"
            return ""

        def checks(s):
            assert s.w["summary"] == "written"
            s.run = e.last_run = CheckRun(round=1)
            return ""

        e.stage_loop.write.side_effect = write
        e.stage_loop.check.side_effect = checks
        ck = None
        for step, following in ((Step.WRITE, Step.LOOK), (Step.LOOK, Step.CHECKS), (Step.CHECKS, Step.REVIEW), (Step.REVIEW, Step.VERIFY)):
            assert round_step(e, step, ck) == following
            saved = e.checkpoints.save.call_args.kwargs
            ck = Checkpoint(bead="t-1", run=e.run_id, t=1, **saved)
            if following is not Step.VERIFY:
                assert ck.progress is not None
                assert ck.progress.write is not None
                assert (ck.n, ck.progress.write.summary) == (1, "written")
        assert ck is not None
        assert (ck.stage, ck.n, ck.rounds, ck.progress) == (1, 0, 0, None)
        assert e.accepted == [0]
        e.stage_loop.write.assert_called_once()
        e.stage_loop.check.assert_called_once()
        e.stage_loop.review.assert_called_once()
