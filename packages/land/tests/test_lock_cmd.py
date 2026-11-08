"""Land-lock command parsing and origin lookup need no processes."""
from argparse import Namespace
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import pytest
from tlkernel.slots import MissingRemote

from tlland.lock_cmd import cmd_land_lock


@pytest.mark.parametrize("cmd_args", [[], ["--"]])
def test_no_command(cmd_args: list[str]) -> None:
    def no_remote(repo: str) -> str:
        pytest.fail("no command must return before looking up the remote")

    def no_lock(cmd: list[str], repo: str, wait: float | None, origin: str) -> int:
        pytest.fail("no command must return before locking the repo")

    stderr = StringIO()
    with redirect_stderr(stderr):
        assert cmd_land_lock(Namespace(cmd_args=cmd_args), no_remote, no_lock) == 2
    assert stderr.getvalue() == "land-lock: no command (usage: tl.py land-lock [--repo DIR] -- CMD...)\n"


@pytest.mark.parametrize("prefix", [[], ["--"]])
def test_command_and_resolved_repo_passed_to_lock(prefix: list[str]) -> None:
    a = Namespace(cmd_args=[*prefix, "echo", "--", "hello"], repo="relative/../repo", wait_min=1.5)
    repo = str(Path(a.repo).resolve())

    def remote_url(where: str) -> str:
        assert where == repo
        return "origin-url"

    def run_locked(cmd: list[str], where: str, wait: float | None, origin: str) -> int:
        assert (cmd, where, wait, origin) == (["echo", "--", "hello"], repo, 1.5, "origin-url")
        return 7

    assert cmd_land_lock(a, remote_url, run_locked) == 7
    assert a.cmd_args == [*prefix, "echo", "--", "hello"]


def test_missing_remote_uses_empty_origin() -> None:
    a = Namespace(cmd_args=["echo"], repo=".", wait_min=None)

    def remote_url(repo: str) -> str:
        raise MissingRemote("origin is missing")

    def run_locked(cmd: list[str], repo: str, wait: float | None, origin: str) -> int:
        assert (cmd, repo, wait, origin) == (["echo"], str(Path(a.repo).resolve()), None, "")
        return 0

    assert cmd_land_lock(a, remote_url, run_locked) == 0
