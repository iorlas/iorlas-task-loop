"""Best-effort run operations leave tracebacks when they fail instead of hiding missing evidence."""
import sys
from pathlib import Path
from unittest import mock

from taskloop.adapters import closes, ident
from tlkernel import childenv
from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.pipeline_ports import FakeLandCleanup, FakeReexecs, FakeTrail

from taskloop.app.asks.closing import ClosingTrust
from taskloop.app.pipeline.closing_branch import ReleaseSlot
from taskloop.app.pipeline.closing_decide import Decide
from taskloop.app.pipeline.journal import Journal
from taskloop.app.pipeline.reflect import Reflector
from taskloop.app.pipeline.reload import Reload
from tlkernel import runoutcome as oc
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.run import RunState


class FailureLogging(Case):
    def assert_traceback(self, text, message):
        assert message in text
        assert "Traceback (most recent call last)" in text

    def test_retry_history_read_failure_is_logged_before_using_empty_history(self):
        host = mock.Mock(bead=BeadId("t-1"))
        host.clock.now.return_value = 100
        with mock.patch("taskloop.adapters.closes.recent_closes", side_effect=OSError("unreadable")), \
                mock.patch.object(Decide, "repo_id", return_value="repo"):
            assert Decide(host, closes.recent_closes).run(oc.make(Kind.PAUSE_LANE, "paused")) == Kind.PAUSE_LANE
        self.assert_traceback(host.warn.call_args.args[0], "could not read retry history: unreadable")

    def test_settle_failure_is_logged_and_does_not_replace_the_run_outcome(self):
        for error in (OSError("disk"), ValueError("record")):
            with self.subTest(error=type(error).__name__):
                host = mock.Mock(run_id="r1")
                with mock.patch("taskloop.app.pipeline.journal.RunLocator"), \
                        mock.patch("taskloop.app.pipeline.journal.finish_run", side_effect=error):
                    Journal(host, lambda: "", lambda _git, _wt: "repo", ident.plugin_version).settle(RunState.PARKED, "paused")
                self.assert_traceback(host.warn.call_args.args[0], "could not settle run r1")

    def test_reflection_catch_all_logs_traceback(self):
        host = mock.Mock()
        host.git.diff_entries.return_value = []
        reflector = Reflector(host, host, host, ClosingTrust(), childenv.delegate_call_env)
        with mock.patch.object(reflector, "worth_asking", return_value=True), \
                mock.patch.object(reflector, "reflect_prompt", side_effect=RuntimeError("prompt")):
            assert reflector.reflect_run("done", "finished") is None
        self.assert_traceback(host.warn.call_args.args[0], "RuntimeError: prompt")

    def test_release_catch_all_logs_traceback(self):
        host = mock.Mock()
        host.claim.slot_bead = ""
        host.tree.leave_slot.side_effect = RuntimeError("slot")
        ReleaseSlot(host, host.tree, FakeLandCleanup()).run("task/t-1", Outcome.PARKED)
        self.assert_traceback(host.log.warn.call_args.args[0], "RuntimeError: slot")

    def test_reload_lookup_catch_all_logs_traceback(self):
        host = mock.Mock(dry=False, argv=["run-task", "t-1"])
        host.newer_fn.side_effect = RuntimeError("lookup")
        Reload(host, host, host, FakeReexecs(), FakeTrail(), lambda: None, lambda: "", childenv, ident).safe_point("land")
        self.assert_traceback(host.warn.call_args.args[0], "RuntimeError: lookup")
