"""R9-04: the host allow is an argv gate, never a shell or executable prefix rule."""

import contextlib
import io
import json
import os
import subprocess
import sys
from unittest import mock

from delegate.app import env
from support.case import Case
from support.procsim import real_proc

import hermetic  # noqa: F401
from test_route import route

ESCAPES = (
    "sed 'e id' f",
    "sed '1e id' f",
    "sed 's/x/id/e' f",
    "sed -f script f",
    "sed --file=script f",
    "sed -n 'w out' f",
    "sed 's/x/y/w out' f",
    "sed --expression='e id' f",
    "sort --compress-program=sh f",
    "sort --compress-prog=sh f",
    "sort -o out f",
    "sort --output=out f",
    "git grep -Osh x",
    "git grep --open-files-in-pager=sh x",
    "git --paginate log",
    "git log --ext-diff",
    "git diff --textconv",
    "git diff --no-index a b --output=out",
    "git -c core.pager=sh log",
    "rg --pre=sh x",
    "rg --hostname-bin=sh x",
    "find . -execdir sh {} +",
    "find . -fprintf out x",
    "jq --run-tests f",
    "jq --raw-output 'debug' f > out",
    "diff --output=out a b",
    "env cat f",
    "xargs cat",
    "nice cat f",
    "timeout 1 cat f",
    "nohup cat f",
    "uv run cat f",
    "npx cat f",
    "make check",
    "just -f other check",
    "cat f & touch out",
    "cat <(touch out)",
)
WRAPPERS = ("env", "sh", "bash", "zsh", "xargs", "nice", "timeout", "nohup", "uv", "npx", "make", "sudo", "command", "exec")


class ExecAllow(Case):
    def setup_method(self):
        self.root = env.config_dir()
        self.host = self.root / "host.json"
        self.doc = {
            "binaries": {"python": sys.executable, "uv": "/opt/pinned/uv", "dotnet": "/opt/pinned/dotnet", "just": "/opt/pinned/just"},
            "writer_exec_allow": [
                ["dotnet", "build"],
                ["dotnet", "test"],
                ["dotnet", "restore"],
                ["dotnet", "--version"],
                ["python", "-m", "unittest"],
                ["python", "-m", "pytest"],
                ["python", "-I", "-B", "-m", "unittest"],
                ["python", "-I", "-B", "-m", "pytest"],
                ["uv", "run", "--no-sync", "--project", ".", "python", "-m", "pytest"],
                ["just", "check"],
            ],
        }
        self.save()

    def save(self):
        self.host.write_text(json.dumps(self.doc))

    def call(self, argv, *flags, spawn=None, exit_code=0):
        """-> (exit code, the posix_spawnp mock the guard starts the command with, stderr); the child is never really started."""
        err = io.StringIO()
        with (
            contextlib.redirect_stderr(err),
            mock.patch("delegate.app.codex_policy.os.posix_spawnp", spawn or mock.Mock(return_value=4242)) as run,
            mock.patch("delegate.app.codex_policy.os.waitpid", return_value=(4242, exit_code << 8)),
            mock.patch("delegate.app.codex_policy.worktree_head", return_value="abc123"),
        ):
            code = route.main(["guard", *flags, "--exec-allow", *argv])
        return code, run, err.getvalue()

    def rows(self):
        """The authorization rows; the `exit` row a started command leaves after it ends is read with `exits`."""
        return [r for r in self.all_rows() if r["mode"] != "exit"]

    def exits(self):
        return [r for r in self.all_rows() if r["mode"] == "exit"]

    def all_rows(self):
        return [json.loads(line) for line in (self.root / "guard.jsonl").read_text().splitlines()]










    @real_proc("delegate: a worker, git or CLI process")
    def test_actual_pinned_python_runs_with_an_empty_path(self):
        command = [sys.executable, str(env.ENTRY), "guard", "--exec-allow", "python", "-m", "unittest", "--help"]
        result = subprocess.run(command, env=os.environ | {"PATH": ""}, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert len(self.rows()) == 1
