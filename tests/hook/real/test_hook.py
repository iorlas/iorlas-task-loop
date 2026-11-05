"""The plugin's hooks (hooks/hook.py): what PreToolUse refuses, what SessionStart and PreCompact do, and that each finishes fast as a real
process. The status and the handoff text they share: size caps and the first line."""
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "hooks" / "hook.py"
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
import tl  # noqa: E402
from support.spawn import port_git  # noqa: E402

from taskloop.contracts.env import snapshot  # noqa: E402
from taskloop.domain.brief import HANDOFF_BYTES, RULES  # noqa: E402
from taskloop.hook import pretool, session  # noqa: E402


def call(tool, **args):
    return pretool.main(json.dumps({"tool_name": tool, "tool_input": args}))


def denied(tool, **args):
    out = call(tool, **args)
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else ""


class Sessions(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.cfg = self.home / "cfg" / "task-loop"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "cfg"),
                                           "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
                                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                           "GIT_COMMITTER_EMAIL": "t@t"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, capture_output=True)
        self.root = self.home / "plugin"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}')
        for name in ("skills/task-loop/tl.py", "hooks/hook.py"):  # a complete install: write_shim skips an incomplete one
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text("")

    def event(self, **kw):
        return json.dumps({"session_id": "s1", "transcript_path": "/t.jsonl", "cwd": str(self.repo), **kw})

    def test_session_start_writes_no_session_index_and_points_the_tl_shim_at_this_install(self):
        assert session.start(self.event(source="startup"), self.root, snapshot(), port_git()) == ""
        assert not (self.cfg / "sessions").exists()
        shim = (self.cfg / "bin" / "tl").read_text()
        assert "exec uv run --quiet --script " + str(self.root / "skills" / "task-loop" / "tl.py") in shim
        assert os.access(self.cfg / "bin" / "tl", os.X_OK)

    def test_session_start_never_fails_on_input_it_cannot_read(self):
        assert session.start("not json", self.root, snapshot(), port_git()) == ""
        assert session.start("", self.root, snapshot(), port_git()) == ""

    def test_a_compaction_writes_the_handoff_and_the_session_that_follows_gets_it_as_context(self):
        assert session.start(self.event(source="compact"), self.root, snapshot(), port_git()) == ""  # nothing written yet
        session.precompact(self.event(), self.root, snapshot(), port_git())
        out = json.loads(session.start(self.event(source="compact"), self.root, snapshot(), port_git()))["hookSpecificOutput"]
        assert out["hookEventName"] == "SessionStart"
        text = out["additionalContext"]
        assert "loop NOT RUNNING" in text
        assert "running 9.9.9" in text
        assert len(text.encode()) <= HANDOFF_BYTES
        for rule in RULES:
            assert rule in text
        fresh = session.start(self.event(source="startup"), self.root, snapshot(), port_git())
        assert fresh == ""  # a fresh session gets no handoff

    def test_a_worktree_shares_the_handoff_of_its_main_checkout(self):
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True, capture_output=True)
        wt = self.home / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "b", str(wt)], check=True, capture_output=True)
        session.precompact(self.event(cwd=str(wt)), self.root, snapshot(), port_git())
        assert (
            "loop NOT RUNNING"
            in json.loads(session.start(self.event(source="compact"), self.root, snapshot(), port_git()))["hookSpecificOutput"][
                "additionalContext"]
        )

    def test_tl_status_and_handoff_read_the_stores(self):
        out = io.StringIO()
        with redirect_stdout(out):
            assert tl.main(["status", "--brief", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop") == 0
        assert out.getvalue().splitlines()[0].startswith("loop NOT RUNNING"), out.getvalue()
        out = io.StringIO()
        with redirect_stdout(out):
            tl.main(["status", "--json", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop")
        assert not json.loads(out.getvalue())["running"]
        out = io.StringIO()
        with redirect_stdout(out):
            assert tl.main(["handoff", "show", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop") == 1
            assert tl.main(["handoff", "write", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop") == 0
            assert tl.main(["handoff", "show", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop") == 0
        assert "standing rules" in out.getvalue()


class Speed(Case):
    """A hook runs before every tool call: pretool imports no store, adapter, app, record or msgspec module; an unknown event fails."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, XDG_CONFIG_HOME=self.tmp.name, CLAUDE_CONFIG_DIR=self.tmp.name)
    def test_pretool_imports_no_store_adapter_app_module_record_or_msgspec(self):
        code = (
            "import sys; sys.path.insert(0, {!r}); from taskloop.hook import main, pretool; pretool.main('{{}}'); "
            "print([m for m in sys.modules if m.startswith(('taskloop.app', 'taskloop.adapters', 'taskloop.stores', 'taskloop.contracts', "
            "'msgspec'))])"
        ).format(str(ROOT / "src"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        assert r.stdout.strip() == "[]"
    def test_pretool_runs_on_the_system_python3_without_uv_or_python_3_15(self):
        system = Path("/usr/bin/python3")
        if not system.exists():
            pytest.skip("no /usr/bin/python3")
        event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pkill -f foo"}})
        r = subprocess.run([str(system), str(HOOK), "pretool"], input=event, capture_output=True, text=True, env=self.env, check=False)
        assert r.returncode == 0, r.stderr
        assert "deny" in r.stdout
