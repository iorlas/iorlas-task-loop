"""Standalone checks open observable runs and seal them on every exit, using fake checks and Git."""
import itertools
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl_main

from taskloop.app.run.stage_run import stage_run
from taskloop.contracts.checks import CheckResult, CheckRun
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import CheckId
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunState
from taskloop.stores.runlog import RunLog


class StageRuns(Case):
    def setup_method(self):
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
            assert bundle.manifest.state == RunState.RUNNING
            assert (
                (bundle.manifest.mode, bundle.manifest.owner, bundle.manifest.session)
                == (f"stage:{verb}", self.who.actor, self.who.session)
            )
            assert (box.run_id, box.run_dir) == (bundle.run, bundle.dir)
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
        assert bundle.manifest.state == state
        assert bundle.manifest.ended is not None
        rows = [json.loads(line) for line in bundle.log.read_text().splitlines()]
        assert {r["run_id"] for r in rows} == {bundle.run}
        assert rows[0]["kind"] == "run_start"
        assert (rows[0]["mode"], rows[0]["owner"], rows[0]["session"]) == (bundle.manifest.mode, self.who.actor, self.who.session)
        assert (rows[-1]["kind"], rows[-1]["outcome"]) == ("close", state.value)
        return bundle

    def test_both_verbs_open_identified_runs_and_keep_successful_evidence(self):
        for verb in ("check", "gate"):
            with self.subTest(verb=verb):
                assert self.invoke(verb).returncode == 0
                bundle = self.assert_ended(RunState.DONE)
                assert (bundle.dir / "evidence.log").read_text() == "fake check evidence"

    def test_red_checks_seal_failed_runs_and_keep_evidence(self):
        red = CheckResult(id=CheckId("unit"), cmd="fake", group="tests", exit=1, status="failed", tail="red")
        for verb in ("check", "gate"):
            with self.subTest(verb=verb):
                result = self.invoke(verb, CheckRun(round=1, results=[red]))
                assert result.returncode == 1
                bundle = self.assert_ended(RunState.FAILED)
                assert str(bundle.dir) in result.stdout
                assert (bundle.dir / "evidence.log").exists()

    def test_exceptions_and_interrupts_also_seal_failed_runs(self):
        for verb in ("check", "gate"):
            for error in (RuntimeError("runner broke"), KeyboardInterrupt()):
                with self.subTest(verb=verb, error=type(error).__name__):
                    with pytest.raises(type(error)):
                        self.invoke(verb, error)
                    self.assert_ended(RunState.FAILED)

    def test_profile_failure_is_inside_the_run_lifecycle(self):
        self.profile.write_text("broken")
        assert self.invoke("check").returncode == 1
        self.assert_ended(RunState.FAILED)

    def test_list_is_also_a_completed_run(self):
        assert self.invoke("gate", None, "--list").returncode == 0
        self.assert_ended(RunState.DONE)

    def test_periodic_heartbeat_advances_while_the_stage_is_open_and_stops_at_exit(self):
        stopped, thread = mock.Mock(), mock.Mock()
        stopped.wait.side_effect = [False, True]
        ticks = itertools.count(1000)
        with mock.patch("taskloop.app.run.stage_run.threading.Event", return_value=stopped), \
             mock.patch("taskloop.app.run.stage_run.threading.Thread", return_value=thread) as make_thread, \
             mock.patch("taskloop.app.run.stage_run.time.time", side_effect=lambda: float(next(ticks))), \
             stage_run(self.who, str(self.repo), "stage:check") as stage:
            before = self.locator.runs()[-1].manifest.heartbeat
            make_thread.call_args.kwargs["target"](*make_thread.call_args.kwargs["args"])
            assert self.locator.runs()[-1].manifest.heartbeat > before
            stage.rc = 0
        stopped.set.assert_called_once()
        thread.join.assert_called_once()
        self.assert_ended(RunState.DONE)

    def test_a_heartbeat_that_cannot_be_written_is_logged_when_it_ends_the_beat_thread(self):
        stopped, thread = mock.Mock(), mock.Mock()
        stopped.wait.side_effect = [False, True]
        with mock.patch("taskloop.app.run.stage_run.threading.Event", return_value=stopped), \
             mock.patch("taskloop.app.run.stage_run.threading.Thread", return_value=thread) as make_thread, \
             mock.patch.object(RunLog, "warn") as warn, \
             stage_run(self.who, str(self.repo), "stage:check") as stage:
            with mock.patch.object(RunLocator, "beat", side_effect=RuntimeError("database is locked")):
                make_thread.call_args.kwargs["target"](*make_thread.call_args.kwargs["args"])
            stage.rc = 0
        assert any("the heartbeat thread died" in str(c.args[0]) and "database is locked" in str(c.args[0]) for c in warn.call_args_list)
