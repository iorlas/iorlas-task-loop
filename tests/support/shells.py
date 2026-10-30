"""A release `Shell` for tests that must not start a process: every command ends 0 with no output, git answers "", and the log is kept."""
from pathlib import Path

from taskloop.app.release.shell import Done, Shell


def quiet_shell(calls: list[list[str]] | None = None) -> Shell:
    log = calls if calls is not None else []

    def run(cmd: list[str], cwd: str | Path | None, check: bool = True, **_: object) -> Done:
        log.append(cmd)
        return Done(0, "", "")

    def git(cwd: str | Path, *a: str, check: bool = True) -> str:
        log.append(["git", *a])
        return ""

    return Shell(git=git, fetch=lambda cwd: None, run=run, say=lambda msg: None)
