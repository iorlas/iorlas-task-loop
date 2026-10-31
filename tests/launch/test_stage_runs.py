"""Standalone checks open observable runs and seal them on every exit, using fake checks and Git."""
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl_main

from taskloop.app.launch.stage_run import stage_run
from taskloop.contracts.checks import CheckResult, CheckRun
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import CheckId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunState


class StageRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        self.profile = self.repo / ".task-loop.json"
        self.profile.write_text('{"engine":{"checks":[]}}')
        self.who = Identity(actor="person", session="session-49", home=str(Path(tmp.name) / "cfg" / "task-loop"))
        self.locator = RunLocator(self.who.config)
        git = mock.Mock(toplevel=mock.Mock(return_value=str(self.repo)), config_get=mock.Mock(return_value=""),
                        common_dir=mock.Mock(return_value=""))
        self.enterContext(mock.patch("tl.real.git", return_value=git))
        self.enterContext(mock.patch("tl.real.spawner", return_value=mock.Mock()))

    def invoke(self, verb, effect=None, *args):
        def run(checker, items, **kwargs):
            box = checker.host
            bundle = self.locator.runs()[-1]
            self.assertEqual(bundle.manifest.state, RunState.RUNNING)
            self.assertEqual((bundle.manifest.mode, bundle.manifest.owner, bundle.manifest.session),
                             (f"stage:{verb}", self.who.actor, self.who.session))
            self.assertEqual((box.run_id, box.run_dir), (bundle.run, bundle.dir))
            (box.run_dir / "evidence.log").write_text("fake check evidence")
            box.log.note("fake check running")
            if isinstance(effect, BaseException):
                raise effect
            return effect or CheckRun(round=1)

        with mock.patch("taskloop.app.launch.check.Checker.run_items", autospec=True, side_effect=run):
            return tl_main(verb, *args, cwd=self.repo, env={
                "XDG_CONFIG_HOME": str(Path(self.who.home).parent),
                "TASK_LOOP_ACTOR": self.who.actor, "TASK_LOOP_SESSION": self.who.session})

    def assert_ended(self, state):
        bundle = self.locator.runs()[-1]
        self.assertEqual(bundle.manifest.state, state)
        self.assertIsNotNone(bundle.manifest.ended)
        rows = [json.loads(line) for line in bundle.log.read_text().splitlines()]
        self.assertEqual({r["run_id"] for r in rows}, {bundle.run})
        self.assertEqual(rows[0]["kind"], "run_start")
        self.assertEqual((rows[0]["mode"], rows[0]["owner"], rows[0]["session"]),
                         (bundle.manifest.mode, self.who.actor, self.who.session))
        self.assertEqual((rows[-1]["kind"], rows[-1]["outcome"]), ("close", state.value))
        return bundle

    def test_both_verbs_open_identified_runs_and_keep_successful_evidence(self):
        for verb in ("check", "gate"):
            with self.subTest(verb=verb):
                self.assertEqual(self.invoke(verb).returncode, 0)
                bundle = self.assert_ended(RunState.DONE)
                self.assertEqual((bundle.dir / "evidence.log").read_text(), "fake check evidence")

    def test_red_checks_seal_failed_runs_and_keep_evidence(self):
        red = CheckResult(id=CheckId("unit"), cmd="fake", group="tests", exit=1, status="failed", tail="red")
        for verb in ("check", "gate"):
            with self.subTest(verb=verb):
                result = self.invoke(verb, CheckRun(round=1, results=[red]))
                self.assertEqual(result.returncode, 1)
                bundle = self.assert_ended(RunState.FAILED)
                self.assertIn(str(bundle.dir), result.stdout)
                self.assertTrue((bundle.dir / "evidence.log").exists())

    def test_exceptions_and_interrupts_also_seal_failed_runs(self):
        for verb in ("check", "gate"):
            for error in (RuntimeError("runner broke"), KeyboardInterrupt()):
                with self.subTest(verb=verb, error=type(error).__name__):
                    with self.assertRaises(type(error)):
                        self.invoke(verb, error)
                    self.assert_ended(RunState.FAILED)

    def test_profile_failure_is_inside_the_run_lifecycle(self):
        self.profile.write_text("broken")
        self.assertEqual(self.invoke("check").returncode, 1)
        self.assert_ended(RunState.FAILED)

    def test_list_is_also_a_completed_run(self):
        self.assertEqual(self.invoke("gate", None, "--list").returncode, 0)
        self.assert_ended(RunState.DONE)

    def test_periodic_heartbeat_advances_while_the_stage_is_open_and_stops_at_exit(self):
        stopped, thread = mock.Mock(), mock.Mock()
        stopped.wait.side_effect = [False, True]
        ticks = itertools.count(1000)
        with mock.patch("taskloop.app.launch.stage_run.threading.Event", return_value=stopped), \
             mock.patch("taskloop.app.launch.stage_run.threading.Thread", return_value=thread) as make_thread, \
             mock.patch("taskloop.app.launch.stage_run.time.time", side_effect=lambda: float(next(ticks))), \
             stage_run(self.who, str(self.repo), "stage:check") as stage:
            before = self.locator.runs()[-1].manifest.heartbeat
            make_thread.call_args.kwargs["target"]()
            self.assertGreater(self.locator.runs()[-1].manifest.heartbeat, before)
            stage.rc = 0
        stopped.set.assert_called_once()
        thread.join.assert_called_once()
        self.assert_ended(RunState.DONE)
