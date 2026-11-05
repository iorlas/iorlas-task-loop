"""The secret guard and git ownership."""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from delegate.adapters import git
from delegate.app import launch
from delegate.domain.policy import worker
from delegate.domain.policy.matchers import heredoc_only_hit, secret_hit
from delegate.domain.policy.shell import git_write, read_only_problem
from delegate.domain.policy.worker import is_policy_denial
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
from test_route import ROOT, _call, route


class SecretGuard:
    def guard(self, tool_input, *flags, tool="X"):
        real = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input})), io.StringIO()
        try:
            return route.main(["guard", *flags])
        finally:
            sys.stdin, sys.stderr = real

    def test_blocks_secret_paths_in_what_is_run_or_opened(self):
        for ti in (
            {"command": "cat ~/.ssh/id_ed25519"},
            {"file_path": "/r/.env"},
            {"command": "cp app/.env.local /tmp"},
            {"path": "/Users/x/.aws"},
            {"pattern": "**/.env"},
            {"command": "cat ~/.config/gh/hosts.yml"},
            {"command": "rg -g '!.git' token .env"},
            {"command": "rg --glob '**/.env' token"},
        ):
            assert self.guard(ti) == 2, ti

    def test_read_only_steps_may_run_reading_commands_only(self):
        for c in (
            "cd /s && git diff 53cc344 -- client; git log --oneline -5",
            "git diff origin/main...HEAD | head -200",
            "rg -n Foo src 2>/dev/null",
            "find . -name '*.cs'",
            "sed -n '1,40p' a.cs",
            "git branch --show-current",
        ):
            assert self.guard({"command": c}, "--read-only", tool="Bash") == 0, c
        for c in (
            "echo x > f",
            "git checkout x",
            "rm -rf a",
            "find . -delete",
            "sed -i s/a/b/ f",
            "git -c core.pager=sh log",
            "cat $(ls)",
            "git diff --output=f",
            "dotnet test",
            "git branch new",
            "rg --pre sh x",
        ):
            assert self.guard({"command": c}, "--read-only", tool="Bash") == 2, c
        assert self.guard({"command": "dotnet test"}, tool="Bash") == 0  # write steps: not limited

    def test_git_writes_are_blocked_for_every_step_and_listings_pass(self):
        for c in (
            "grep -n '' justfile | head; git stash list >/dev/null; git diff HEAD --stat -- justfile",  # lifesim-q21f
            "git ls-files | grep -i x; git log -1 --format=%h -- a | head -1; git branch --contains 0dedd418 2>&1 | head -3",
            "git branch -a",
            "git tag -l 'v*'",
            "git worktree list",
            "git stash show -p",
        ):
            assert self.guard({"command": c}, tool="Bash") == 0, c
            assert self.guard({"command": c}, "--read-only", tool="Bash") == 0, c
        for c in (
            "git stash",
            "git branch new",
            "git tag v1",
            "git checkout -b x",
            "cd a && git commit -m x",
            "ls; git push",
            "git -C /x reset --hard",
        ):
            assert self.guard({"command": c}, tool="Bash") == 2, c
            assert is_policy_denial(*_call({"tool_name": "Bash", "tool_input": {"command": c}})), c

    def test_excluding_secret_paths_in_quoted_and_wrapped_searches_is_not_touching_them(self):
        real = (
            "/bin/zsh -lc \"rg --files --hidden -g '*SKILL.md' -g '\"'!'\"\\\\.git' -g '\"'!'\"\\\\.beads/**' -g '\"'!'\"\\\\.task/**' "
            "-g '\"'!'\"\\\\.env*' -g '\"'!**/node_modules/**'\"' -g '\"'!**/.venv/**'\"'\""
        )
        for c in (
            real,
            "rg -n --hidden -g '!config' -g '!.git/**' -g '!.beads/**' -g '!.env*' foo",
            "rg --files --hidden -g AGENTS.md -g '!.git' -g '!.beads' -g '!.env*'",
            "bash -c \"zsh -c 'rg x --glob=!.env'\"",
            "find . -not -path './.env*'",
            "find . ! -path '*/.ssh/*'",
        ):
            assert secret_hit(c) is None
            assert read_only_problem(c) is None
            assert self.guard({"command": c}, "--read-only", tool="Bash") == 0, c
        for c in ("cat .env", "rg foo .env", "rg -g '.env*' foo", "cat ~/.ssh/id_rsa", 'bash -lc "cat .env"', "rg -g '!x' foo .env"):
            assert secret_hit(c), c
            assert self.guard({"command": c}, tool="Bash") == 2, c
        assert read_only_problem("bash -lc 'rm x'") == "`rm` is not a reading command"

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

    def test_writer_briefs_say_to_edit_with_apply_patch(self):
        assert "apply_patch" in worker.EDIT_RULE
        assert worker.EDIT_RULE in launch.PREAMBLE

    def test_lets_through_lookalikes_and_written_content(self):
        for ti in (
            {"command": "cat .env.example"},
            {"command": "node -e 'process.env.HOME'"},
            {"command": "dotnet test"},
            {"file_path": "src/environment.ts"},
            {"file_path": ".gitignore", "content": ".env\n.ssh/"},
            {"command": "ls .envrc"},
            {
                "command": "/bin/zsh -lc \"head -45 client/Assets/Tests/Editor/LiveViewTests.cs; rg -n --hidden --glob '!**/.git/**' "
                "--glob '!**/.env*' --glob '!**/.aws/**' '^(<<<<<<<|>>>>>>>)( |$)' .\""
            },  # lifesim-6dq0: excluding is avoiding
            {"command": "grep -r --exclude=.env --exclude-dir=.ssh foo ."},
            {"command": "find . -not -path '*/.ssh/*'"},
            {"command": "git ls-files ':!.env'"},
        ):
            assert self.guard(ti) == 0, ti


class GitOwnership:
    """Workers must not change git state; the coordinator owns branches, commits and worktrees."""

    def setup_method(self):
        self.sp = subprocess
        self.tmp = tempfile.TemporaryDirectory()
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
        wt = tempfile.mkdtemp()
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
        with tempfile.TemporaryDirectory() as d:
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
