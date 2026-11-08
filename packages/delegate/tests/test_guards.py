"""The secret guard and git ownership."""

import io
import json
import sys

import hermetic  # noqa: F401  (a home of its own for every test)
from test_route import _call, route

from delegate.app import launch
from delegate.domain.policy import worker
from delegate.domain.policy.matchers import secret_hit
from delegate.domain.policy.shell import read_only_problem
from delegate.domain.policy.worker import is_policy_denial


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
            {"command": "cp app/.env.local /srv"},
            {"path": "/Users/x/.aws"},
            {"pattern": "**/.env"},
            {"command": "cat ~/.config/gh/hosts.yml"},
            {"command": "rg -g '!.git' token .env"},
            {"command": "rg --glob '**/.env' token"},
        ):
            assert self.guard(ti) == 2, ti

    def test_blocks_the_engines_own_state_and_every_auth_file(self):
        for ti in (
            {"command": "sqlite3 ~/.config/task-loop/factory.db .dump"},
            {"command": "cat ~/.config/task-loop/githooks/pre-push"},
            {"file_path": "/home/x/.config/task-loop/events.jsonl"},
            {"command": "cat $CODEX_HOME/auth.json"},
            {"command": "cat /var/overlay-x/auth.json"},
            {"command": "cat ~/.local/share/opencode/auth.json"},
        ):
            assert self.guard(ti) == 2, ti
        for ti in ({"command": "cat docs/task-loop.md"}, {"command": "rg author.json src"}):
            assert self.guard(ti) == 0, ti

    def test_a_worker_cannot_write_delegates_own_state(self):
        """routing.json, history.jsonl and state.json live under the config dir; a writer edits none of them (tl-7i9k.53, M-059)."""
        for ti in (
            {"file_path": "/home/x/.config/task-loop/delegate/routing.json", "content": "{}"},
            {"command": "echo '{}' > ~/.config/task-loop/delegate/history.jsonl"},
            {"command": "sed -i s/a/b/ $HOME/.config/task-loop/delegate/state.json"},
            {"command": "tee ~/.config/task-loop/delegate/routing.json < x"},
            {"command": "cp x ~/.config/task-loop/delegate/"},
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
