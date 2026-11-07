"""Release failure records and the final status line retain multiline refusal reasons."""
import io
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tlkernel.env import Env
from tlkernel.slots import SlotGitError
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

from tlrelease import flow, publish
from tlrelease.shell import Abort
from tlrelease.testing import FakeReleaseHost


class FailureSummary(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_failed_release_keeps_the_reason_in_the_record_comment_and_final_line(self):
        refusal = "! [remote rejected] main -> main (pre-receive hook declined)"
        message = "the push was refused and origin/main did not move:\n" + refusal
        for version in ("", "0.23.325"):
            with self.subTest(version=version):
                prefix = f"{version} was pushed but " if version else "nothing released: "
                expected = prefix + "the push was refused and origin/main did not move: | " + refusal
                self.check_failure(Abort(message, version=version, log="suite.log"), expected)

    def test_failure_summary_is_bounded_and_empty_messages_have_a_fallback(self):
        self.check_failure(Abort("refused\n" + "x" * 600), "nothing released: refused | " + "x" * 472)
        self.check_failure(Abort("\n"), "nothing released: failed")

    def check_failure(self, error: Abort, expected: str):
        port, spawner, store = mock.Mock(), mock.Mock(), mock.Mock()
        port.remote_url.return_value = "origin"
        output = io.StringIO()
        rig = FakeReleaseHost(self.root)
        host = replace(rig.host, bd_store=lambda actor, repo: store)
        with (mock.patch.object(flow, "release_lock_path", return_value=Path("release.lock")),
              mock.patch.object(flow.clone, "ready", return_value=Path("clone")),
              mock.patch.object(flow.selfupdate, "newer_release", return_value=None),
              mock.patch.object(flow, "release", side_effect=error),
              mock.patch.object(flow, "ReleaseResultStore") as results,
              redirect_stderr(output)):
            code = flow.main(["fix", "--bead", "tl-v11i"], Path("tool"), spawner, port,
                             Env({"XDG_CONFIG_HOME": str(self.root / "cfg")}), mock.Mock(),
                             clock=lambda: 1.0, host=host)
        assert code == 1
        result = results.return_value.write.call_args.args[0]
        assert result.summary == expected
        assert result.log == error.log
        assert "\n" not in result.summary
        assert len(result.summary) <= 500
        assert output.getvalue().splitlines()[-1] == "release FAILED: " + expected + (f" (log {error.log})" if error.log else "")
        store.add_comment.assert_called_once_with("tl-v11i", "release FAILED: " + expected +
                                                  ("; log " + error.log if error.log else ""))

    def test_tag_warning_uses_the_push_rejection_tail(self):
        sh = mock.Mock()
        sh.port.rev_parse.return_value = ""
        sh.port.push.side_effect = SlotGitError("remote: tag policy refused | ! [remote rejected] v1.2.3")
        publish.tag(Path("repo"), "v1.2.3", "the plugin repo", sh)
        sh.say.assert_called_once_with("warning: tag v1.2.3 in the plugin repo failed: "
                                       "remote: tag policy refused | ! [remote rejected] v1.2.3")
