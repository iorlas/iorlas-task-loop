"""What every step of a release shares: its refusal, the git and process calls (through its edge's Spawner), and its voice."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from taskloop.contracts.env import Env
from taskloop.contracts.ports import Git, Spawner
from taskloop.contracts.slots import SlotGitError


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


def fetch_or_abort(git: Git, cwd: str | Path) -> None:
    """A fetch into the repo (the port's fetch survives a ref-lock race with a loop's fetch at the same moment); a failure aborts."""
    try:
        git.fetch(str(cwd))
    except SlotGitError as e:
        raise Abort(f"git fetch failed in {cwd}:\n{e.tail[-2000:]}") from None


def say(msg: str) -> None:
    print("release: " + msg, flush=True)


@dataclass(frozen=True)
class Shell:
    """The calls a release step makes to the outside; `of(spawner, port)` builds the real ones, a test hands a step its own.
    `run(cmd, cwd, check)`: `extra` goes over the child's environment, `timeout_s` ends it (exit 124). `port`: the Git port, which every
    step that reads or moves refs asks (clone, push, publish, tidy)."""
    fetch: Callable[[str | Path], None]
    run: Callable[..., Finished]
    say: Callable[[str], None]
    port: Git
    spawner: Spawner  # the same one `run` goes through, for the calls that stream (the suite's pytest runs)
    env: Env = field(default_factory=Env)  # the process environment taken at the edge: the suite's settings and the base of its children


def of(spawner: Spawner, port: Git, env: Env) -> Shell:
    """The shell whose every process is started through `spawner`, and whose git port is `port`."""
    def run(cmd: list[str], cwd: str | Path | None, check: bool = True, *, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None) -> Done:
        r = spawner.run(cmd, cwd=None if cwd is None else str(cwd), extra=extra, timeout_s=timeout_s)
        if check and r.exit:
            raise Abort("{} failed in {}:\n{}".format(" ".join(cmd), cwd, (r.out + r.err).strip()[-2000:]))
        return Done(r.exit, r.out, r.err)

    return Shell(fetch=lambda cwd: fetch_or_abort(port, cwd), run=run, say=say, port=port, spawner=spawner, env=env)
