"""SessionStart introduces task-loop only in profile repos and survives hook failures."""
import json
from pathlib import Path
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.domain import selfdescribe
from taskloop.hook import session
from tlkernel.env import Env


class SessionContext(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.env = Env()
        self.git = mock.Mock()
        self.git.common_dir.return_value = str(self.repo / ".git")
        for name in ("ensure_machine",):
            patch = mock.patch.object(session.install, name)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(session.handoff, "read", return_value="")
        self.read = patch.start()
        self.addCleanup(patch.stop)

    def start(self, source):
        event = json.dumps({"cwd": str(self.repo), "source": source})
        return session.start(event, self.repo, self.env, self.git)

    def profile(self):
        (self.repo / ".task-loop.json").write_text("{}", encoding="utf-8")

    def test_all_session_sources_get_context_in_a_profile_repo(self):
        self.profile()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                out = json.loads(self.start(source))["hookSpecificOutput"]
                assert out["hookEventName"] == "SessionStart"
                assert out["additionalContext"] == selfdescribe.text()

    def test_no_profile_adds_no_context(self):
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                assert self.start(source) == ""

    def test_compact_introduction_precedes_handoff_with_a_blank_line(self):
        self.profile()
        self.read.return_value = "handoff text"
        context = json.loads(self.start("compact"))["hookSpecificOutput"]["additionalContext"]
        assert context == selfdescribe.text() + "\n\nhandoff text"

    def test_handoff_without_a_profile_is_preserved(self):
        self.read.return_value = "handoff text"
        context = json.loads(self.start("compact"))["hookSpecificOutput"]["additionalContext"]
        assert context == "handoff text"

    def test_startup_does_not_read_a_handoff(self):
        self.profile()
        self.start("startup")
        self.read.assert_not_called()

    def test_a_worktree_uses_its_main_checkouts_profile(self):
        self.profile()
        worktree = self.repo / "slot"
        worktree.mkdir()
        event = json.dumps({"cwd": str(worktree), "source": "startup"})
        out = session.start(event, self.repo, self.env, self.git)
        assert json.loads(out)["hookSpecificOutput"]["additionalContext"] == selfdescribe.text()
        self.git.common_dir.assert_called_once_with(str(worktree))

    def test_a_profile_check_failure_returns_empty_text(self):
        with mock.patch.object(Path, "is_file", side_effect=OSError("unavailable")):
            assert self.start("startup") == ""

    def test_hook_failures_return_empty_text(self):
        for name in ("ensure_machine", "repo_of", "self_description"):
            with self.subTest(name=name), mock.patch.object(session.install, name, side_effect=RuntimeError("unavailable")):
                assert self.start("startup") == ""
        with mock.patch.object(session.handoff, "read", side_effect=OSError("unavailable")):
            assert self.start("compact") == ""

    def test_unreadable_input_returns_empty_text(self):
        for event in ("not json", "", "[]", "null"):
            with self.subTest(event=event):
                assert session.start(event, self.repo, self.env, self.git) == ""
