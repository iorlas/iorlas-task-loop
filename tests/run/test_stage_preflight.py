"""Hand stage runs must disclose WIP and preview without opening an engine."""
import contextlib
import io
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.builders import cfg_with
from support.fakes import FakeBeadStore, FakeClock, FakeRouter
from support.tlmain import tl

from taskloop.app.run import entry
from taskloop.app.run.engine import Engine
from taskloop.app.run.layout import RunLayout
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Result, Step
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import StatusRow
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.ports import Git
from taskloop.contracts.run import RunReport, RunState
from taskloop.stores.memory import fake_stores


class StagePreflight(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wt = self.root / "worktree"
        self.wt.mkdir()
        self.who = Identity(actor="mac-owner", session="mac-session", home=str(self.root / "config"))
        self.locator = RunLocator(self.who.config)
        self.git = mock.Mock(spec=Git)
        self.git.common_dir.return_value = ""
        self.git.status.return_value = []
        self.git.branch.return_value = "task/t-1"
        self.git.toplevel.return_value = str(self.wt)
        self.git.unpinned.return_value = self.git
        self.git.config_entries.return_value = []
        self.git.rev_parse.return_value = "head"
        self.git.remote_url.return_value = ""
        self.git.config_get.return_value = ""
        self.git.merge_base.return_value = "base"
        self.git.ls_tree.return_value = []
        self.cfg, self.env = EngineConfig(), Env()
        self.spawner = mock.Mock()
        self.store = FakeBeadStore()
        self.a = Namespace(id=BeadId("t-1"), worktree=str(self.wt), slot=None, dry_run=True, fresh=False,
                            force=False, stage="gate", loop=False, quiet=True, outcome_file=str(self.root / "outcome"))
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))

    def run_in(self):
        return entry.run_in(self.a, str(self.wt), self.cfg, self.store, env=self.env,
                            spawner=self.spawner, git=self.git, who=self.who)

    def run_bead(self):
        return entry.run_bead(self.a, str(self.wt), self.cfg, str(self.wt), self.store, env=self.env,
                              spawner=self.spawner, git=self.git, who=self.who)

    def untouched(self):
        self.git.stage_literal.assert_not_called()
        self.git.try_commit.assert_not_called()
        self.git.tree_of.assert_not_called()
        self.spawner.run.assert_not_called()
        self.assertFalse(self.who.config.runs_dir().exists())
        self.assertEqual(list(self.wt.iterdir()), [])
        self.assertFalse((self.root / "outcome").exists())
        self.assertEqual(self.store.calls, [])

    def test_gate_dry_run_prints_plan_without_steps_commits_manifest_or_worktree_writes(self):
        with mock.patch.object(entry, "Engine") as engine:
            self.assertEqual(self.run_in(), 0)
        engine.assert_not_called()
        self.untouched()
        for text in ("stage gate", str(self.wt), "slot:", "lease:", "branch: task/t-1", "refusals: none"):
            self.assertIn(text, self.output.getvalue())

    def test_auto_next_dry_run_and_unspecified_worktree_do_not_create_a_worktree(self):
        self.a.stage, self.a.worktree = None, None
        self.assertEqual(self.run_in(), 0)
        self.assertIn("next stage: reset", self.output.getvalue())
        self.untouched()

    def test_any_slot_dry_run_does_not_take_or_wait_for_a_slot(self):
        self.a.slot, self.a.worktree = "any", None
        with mock.patch.object(entry.wslots, "wait_slot") as wait:
            self.assertEqual(entry.run_any_slot(self.a, str(self.wt), self.cfg, self.store, env=self.env,
                                               spawner=self.spawner, git=self.git, who=self.who), 0)
        wait.assert_not_called()
        self.untouched()

    def test_dry_run_reports_land_and_close_refusals_without_running_a_plan_command(self):
        self.cfg = cfg_with(gate=["true"], plan_cmd=["plan-producer"])
        for step, reason in (("land", "no green gate"), ("close", "no land on record")):
            with self.subTest(step=step):
                self.a.stage = step
                self.assertEqual(self.run_in(), 1)
                self.assertIn(reason, self.output.getvalue())
        self.untouched()

    def test_clean_land_preview_accepts_cached_green_without_writing_slot_folders(self):
        self.a.stage = "land"
        self.cfg = cfg_with(gate=["true"], plan_cmd=["plan-producer"])
        with mock.patch("taskloop.app.checks.runner.RunMemo.has", return_value=True) as cached:
            self.assertEqual(self.run_in(), 0)
        self.assertTrue(cached.called)
        self.untouched()
        self.assertFalse(self.who.config.root.exists())

    def test_live_previous_run_refuses_explicit_and_auto_dry_runs_without_changing_manifest(self):
        old = self.locator.create(str(self.wt), "t-1", 1)
        before = self.who.config.run_manifest(old.run).read_bytes()
        for stage in ("gate", None):
            self.a.stage = stage
            self.assertEqual(self.run_in(), 1)
        self.assertIn(f"previous run {old.run} is still created", self.output.getvalue())
        self.assertEqual(self.who.config.run_manifest(old.run).read_bytes(), before)
        self.assertEqual(len(self.locator.runs()), 1)
        self.git.try_commit.assert_not_called()
        self.spawner.run.assert_not_called()

    def dirty_previous(self, state):
        previous = self.locator.create(str(self.wt), "t-1", 1)
        self.locator.advance(previous.run, Step.GATE)
        self.locator.end(previous.run, 2, state)
        self.git.status.return_value = [StatusRow(path="src/main.py", index=" ", work="M"),
                                       StatusRow(path="new file.txt", index="?", work="?")]

    def test_dirty_stopped_parked_or_failed_preview_requires_force_before_engine_or_claim(self):
        for state in (RunState.STOPPED, RunState.PARKED, RunState.FAILED):
            for stage in ("gate", None):
                with self.subTest(state=state, stage=stage):
                    self.dirty_previous(state)
                    self.a.stage = stage
                    with mock.patch.object(entry, "Engine") as engine:
                        result = self.run_in()
                    self.assertEqual(result, 1)
                    engine.assert_not_called()
        for text in (str(self.wt), "2 files", "src/main.py", "new file.txt", "--force"):
            self.assertIn(text, self.output.getvalue())
        self.assertEqual(len(self.locator.runs()), 6)
        self.git.stage_literal.assert_not_called()
        self.git.try_commit.assert_not_called()
        self.assertEqual(self.store.calls, [])

    def test_explicit_stage_requires_force_before_engine_or_claim(self):
        self.dirty_previous(RunState.STOPPED)
        self.a.dry_run = False
        with mock.patch.object(entry, "Engine") as engine:
            self.assertEqual(self.run_bead().outcome, Result.FAILED)
        engine.assert_not_called()
        self.assertEqual(self.store.calls, [])

    def test_preview_skips_status_outside_the_beads_own_checkout(self):
        for branch, top in (("", ""), ("main", str(self.wt)),
                            ("task/other", str(self.wt)), ("task/t-1", str(self.root))):
            with self.subTest(branch=branch, top=top):
                self.git.branch.return_value = branch
                self.git.toplevel.return_value = top
                self.git.status.side_effect = AssertionError("status requires the bead's checkout")
                self.assertEqual(self.run_in(), 0)
        self.git.status.assert_not_called()
        self.untouched()

    def test_plain_run_without_stage_bypasses_preflight_and_its_git_calls(self):
        self.a.dry_run, self.a.stage, self.a.outcome_file = False, None, None
        with mock.patch.object(entry, "release_dead"), mock.patch.object(entry, "parked", return_value=""), \
                mock.patch.object(entry, "admit", return_value=(True, "")), \
                mock.patch.object(entry.verbs, "claim", return_value=0), mock.patch.object(entry.fence, "take"), \
                mock.patch.object(entry.preflight, "inspect", side_effect=AssertionError("plain run preflight")), \
                mock.patch.object(entry, "Engine") as engine:
            engine.return_value.run.return_value = 0
            engine.return_value.result.return_value = RunReport(outcome=Result.LANDED, bead=self.a.id)
            self.assertEqual(self.run_bead(), 0)
            engine.return_value.run.assert_called_once_with(stage=None, continuous=False)
        self.assertEqual(self.git.mock_calls, [])

    def test_fresh_does_not_authorize_committing_dirty_work(self):
        self.dirty_previous(RunState.STOPPED)
        self.a.dry_run, self.a.fresh = False, True
        with mock.patch.object(entry, "Engine") as engine:
            self.assertEqual(self.run_bead().outcome, Result.FAILED)
        engine.assert_not_called()

    def test_force_proceeds_after_listing_paths_and_loop_bypasses_hand_admission(self):
        self.dirty_previous(RunState.STOPPED)
        self.a.dry_run, self.a.outcome_file = False, None
        with mock.patch.object(entry, "release_dead"), mock.patch.object(entry, "parked", return_value=""), \
                mock.patch.object(entry, "admit", return_value=(True, "")), \
                mock.patch.object(entry.verbs, "claim", return_value=0), mock.patch.object(entry.fence, "take"), \
                mock.patch.object(entry, "Engine") as engine:
            engine.return_value.run.return_value = 0
            engine.return_value.result.return_value = RunReport(outcome=Result.LANDED, bead=self.a.id)
            self.a.force = True
            self.assertEqual(self.run_bead(), 0)
            engine.return_value.run.assert_called_once_with(stage="gate", continuous=False)
            self.assertEqual(engine.call_args.kwargs["mode"], "stage:gate")
            self.assertIn("2 files", self.output.getvalue())
            self.a.force, self.a.loop, self.a.stage = False, True, None
            self.assertEqual(self.run_bead(), 0)
            self.assertEqual(engine.call_args.kwargs["mode"], "loop")

    def test_parser_accepts_force_alongside_stage_and_fresh(self):
        a = tl.build_parser().parse_args(["run-task", "t-1", "--stage", "gate", "--fresh", "--force"])
        self.assertTrue(a.force)
        self.assertTrue(a.fresh)

    def test_engine_manifest_is_identified_before_stage_dispatch_and_gate_keeps_identity(self):
        e = Engine(self.a.id, str(self.wt), self.cfg, store=self.store, route=FakeRouter(), clock=FakeClock(),
                   stores=fake_stores(), env=self.env, spawner=self.spawner, git=self.git, who=self.who, mode="stage:gate")
        opened = self.locator.get(e.run_id)
        assert opened is not None
        self.assertEqual((opened.manifest.mode, opened.manifest.owner, opened.manifest.session),
                         ("stage:gate", "mac-owner", "mac-session"))
        with mock.patch("taskloop.app.run.stages.Lease"), mock.patch.object(e.ask_flow, "check"), \
                mock.patch.object(e.briefs, "export"), mock.patch.object(e.lander.gate, "run", return_value=object()):
            self.assertEqual(e.run(stage="gate", continuous=False), 0)
        completed = self.locator.get(e.run_id)
        assert completed is not None
        manifest = completed.manifest
        self.assertEqual((manifest.mode, manifest.owner, manifest.session, manifest.state),
                         ("stage:gate", "mac-owner", "mac-session", RunState.DONE))

    def test_layout_identifies_taken_up_run_as_well_as_new_runs(self):
        previous = self.locator.create(str(self.wt), "t-1", 1)
        layout = RunLayout.open("t-1", self.wt, previous.run, self.who.config, str(self.wt), 2,
                                mode="auto-next", owner=self.who.actor, session=self.who.session)
        opened = self.locator.get(layout.run)
        assert opened is not None
        manifest = opened.manifest
        self.assertEqual((manifest.mode, manifest.owner, manifest.session, manifest.attempts),
                         ("auto-next", "mac-owner", "mac-session", 2))
