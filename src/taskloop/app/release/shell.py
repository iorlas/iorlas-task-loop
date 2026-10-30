"""What every step of a release shares: its refusal, the git and process calls (through its edge's Spawner), and its voice."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taskloop.adapters import gitrepo
from taskloop.contracts.ports import Spawner


class Abort(Exception):
    """A refusal or failure that stops the release. `log`: the saved full suite output; `tests`: the failing test ids;
    `version`: set once main was pushed (the failure came after, e.g. the install)."""

    def __init__(self, msg: str, log: object = "", tests: tuple[str, ...] | list[str] = (), version: str = "") -> None:
        super().__init__(msg)
        self.log, self.tests, self.version = str(log or ""), list(tests), version


class Finished(Protocol):
    @property
    def returncode(self) -> int: ...
    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...


@dataclass(frozen=True)
class Done:
    """What a finished command printed and how it ended (the words of subprocess.CompletedProcess, which a test's fake may return)."""
    returncode: int
    stdout: str
    stderr: str


def fetch(cwd: str | Path) -> None:
    """A fetch into the repo, again while it loses a ref lock to a loop's fetch at the same moment (gitrepo.fetch)."""
    r = gitrepo.fetch(str(cwd))
    if r.returncode:
        raise Abort(f"git fetch failed in {cwd}:\n{r.stderr.strip()[-2000:]}")


def say(msg: str) -> None:
    print("release: " + msg, flush=True)


@dataclass(frozen=True)
class Shell:
    """The four calls a release step makes to the outside; `of(spawner)` builds the real ones, a test hands a step its own.
    `run(cmd, cwd, check)`: `extra` goes over the child's environment, `timeout_s` ends it (exit 124)."""
    git: Callable[..., str]
    fetch: Callable[[str | Path], None]
    run: Callable[..., Finished]
    say: Callable[[str], None]


def of(spawner: Spawner) -> Shell:
    """The shell whose every process is started through `spawner`."""
    def run(cmd: list[str], cwd: str | Path | None, check: bool = True, *, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None) -> Done:
        r = spawner.run(cmd, cwd=None if cwd is None else str(cwd), extra=extra, timeout_s=timeout_s)
        if check and r.exit:
            raise Abort("{} failed in {}:\n{}".format(" ".join(cmd), cwd, (r.out + r.err).strip()[-2000:]))
        return Done(r.exit, r.out, r.err)

    def git(cwd: str | Path, *a: str, check: bool = True) -> str:
        return run(["git", *a], cwd, check).stdout.strip()

    return Shell(git=git, fetch=fetch, run=run, say=say)
