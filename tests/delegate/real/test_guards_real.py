"""The secret guard and git ownership."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import hermetic  # noqa: F401  (a home of its own for every test)
from support.procsim import real_proc
from test_route import ROOT, route

from delegate.adapters import git
from delegate.domain.policy.matchers import heredoc_only_hit, secret_hit
from delegate.domain.policy.shell import git_write
from tltestkit.tmpdir import TemporaryDirectory, mkdtemp


class SecretGuard:
    def guard(self, tool_input, *flags, tool="X"):
        real = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input})), io.StringIO()
        try:
            return route.main(["guard", *flags])
        finally:
            sys.stdin, sys.stderr = real





    @real_proc("delegate: a worker, git or CLI process")
    def test_heredoc_body_secret_name_gets_an_apply_patch_hint_and_real_reads_do_not(self):
        hd = "zsh -lc \"python - <<'EOF'\nif path.name == '.env':\n    pass\nEOF\""
        assert heredoc_only_hit(hd)
        assert secret_hit(hd)  # still blocked
        for c in ("python -c \"open('.env')\"", "cat .env", "cat .env <<'EOF'\nx\nEOF"):
            assert not heredoc_only_hit(c), c
            assert secret_hit(c), c
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "delegate" / "entry.py"), "guard"],
            capture_output=True,
            text=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": hd}}),
            check=False,
        )
        assert r.returncode == 2
        assert "apply_patch" in r.stderr
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "delegate" / "entry.py"), "guard"],
            capture_output=True,
            text=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}),
            check=False,
        )
        assert "apply_patch" not in r.stderr




class GitOwnership:
    """Workers must not change git state; the coordinator owns branches, commits and worktrees."""

    def setup_method(self):
        self.sp = subprocess
        self.tmp = TemporaryDirectory()
        self.dir = self.tmp.name

        def run(*a):
            return subprocess.run(["git", "-C", self.dir, *a], capture_output=True, text=True, check=True)

        self.git = run
        run("init", "-q")
        run("config", "user.email", "t@example.com")
        run("config", "user.name", "t")
        Path(self.dir, "f.txt").write_text("1")
        run("add", ".")
        run("commit", "-qm", "init")

    def teardown_method(self):
        self.tmp.cleanup()

    @real_proc("delegate: a worker, git or CLI process")
    def test_editing_files_is_clean(self):
        before = git.state(self.dir)
        Path(self.dir, "f.txt").write_text("2")
        Path(self.dir, "new.txt").write_text("x")
        assert git.changes(before, git.state(self.dir)) == []

    @real_proc("delegate: a worker, git or CLI process")
    def test_branch_and_head_changes_are_reported_other_refs_and_worktrees_are_not(self):
        before = git.state(self.dir)
        wt = mkdtemp()
        self.git("worktree", "add", "-q", os.path.join(wt, "w"), "-b", "other")  # parallel slots do this all the time
        assert git.changes(before, git.state(self.dir)) == []
        self.git("checkout", "-qb", "feature")
        Path(self.dir, "f.txt").write_text("3")
        self.git("commit", "-qam", "x")
        text = " ".join(git.changes(before, git.state(self.dir)))
        assert "branch" in text
        assert "HEAD" in text

    @real_proc("delegate: a worker, git or CLI process")
    def test_not_a_repo_is_a_no_op(self):
        with TemporaryDirectory() as d:
            assert git.state(d) is None
            assert git.changes(None, None) == []

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_guard_blocks_every_git_write(self):
        for c in (
            "git commit -m x",
            "git push",
            "git checkout x",
            "git switch x",
            "git branch x",
            "git worktree add y",
            "git merge x",
            "git rebase x",
            "git reset --hard",
            "git stash",
            "git cherry-pick a",
            "git tag v",
            "git revert a",
            "git am p",
            "git pull",
        ):
            assert git_write(c), c
