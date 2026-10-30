"""A release `Shell` for tests that must not start a process: every command ends 0 with no output and the log is kept. Its git port
is the real one: a test that must not start git puts the gitsim in."""
from pathlib import Path

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.release.shell import Done, Shell
from taskloop.contracts.env import Env


def quiet_shell(calls: list[list[str]] | None = None) -> Shell:
    log = calls if calls is not None else []

    def run(cmd: list[str], cwd: str | Path | None, check: bool = True, **_: object) -> Done:
        log.append(cmd)
        return Done(0, "", "")

    return Shell(fetch=lambda cwd: None, run=run, say=lambda msg: None, port=RealGit(), spawner=RealSpawner(Env()))
