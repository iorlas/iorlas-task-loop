"""What every step of a release shares: its refusal, the git and process calls, and its one-line voice."""
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.adapters import gitrepo


class Abort(Exception):
    """A refusal or failure that stops the release. `log`: the saved full suite output; `tests`: the failing test ids;
    `version`: set once main was pushed (the failure came after, e.g. the install)."""

    def __init__(self, msg: str, log: object = "", tests: tuple[str, ...] | list[str] = (), version: str = "") -> None:
        super().__init__(msg)
        self.log, self.tests, self.version = str(log or ""), list(tests), version


def run(cmd: list[str], cwd: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if check and r.returncode:
        raise Abort("{} failed in {}:\n{}".format(" ".join(cmd), cwd, (r.stdout + r.stderr).strip()[-2000:]))
    return r


def git(cwd: str | Path, *a: str, check: bool = True) -> str:
    return run(["git", *a], cwd, check).stdout.strip()


def fetch(cwd: str | Path) -> None:
    """A fetch into the repo, again while it loses a ref lock to a loop's fetch at the same moment (gitrepo.fetch)."""
    r = gitrepo.fetch(str(cwd))
    if r.returncode:
        raise Abort(f"git fetch failed in {cwd}:\n{r.stderr.strip()[-2000:]}")


def say(msg: str) -> None:
    print("release: " + msg, flush=True)


@dataclass(frozen=True)
class Shell:
    """The four calls a release step makes to the outside; a test hands a step its own."""
    git: Callable[..., str] = git
    fetch: Callable[[str | Path], None] = fetch
    run: Callable[..., subprocess.CompletedProcess[str]] = run
    say: Callable[[str], None] = say


REAL = Shell()
