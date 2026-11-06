"""What the checks need of the engine that runs them, and the two ways a round stops the run."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from taskloop.app.checks.checklog import CheckLog
from taskloop.contracts.checks import CheckFaultKind
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.env import Env
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git, Spawner
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class CheckFault(Exception):
    """A check ended the run's step: the engine turns it into a Blocked of the matching kind."""

    def __init__(self, kind: CheckFaultKind, text: str, rc: int | None = None) -> None:
        super().__init__(text)
        self.kind = kind
        self.text = text
        self.rc = rc  # the exit code of the check that caused it


class CheckStuck(Exception):
    """The same checks were red with the same output in `rounds` rounds in a row: more writes will not fix it. `signature` names them."""

    def __init__(self, signature: str, rounds: int) -> None:
        super().__init__(signature)
        self.signature = signature
        self.rounds = rounds


class CheckSteps(Protocol):
    """The run's step book, as the checks use it."""

    @property
    def id(self) -> str: ...
    def begin(self, step: str, text: str, **meta: object) -> object: ...
    def outcome(self, outcome: str, detail: str = ...) -> object: ...


class CheckoutView(Protocol):
    """The slot's checkout (app/land/checkout.py), as the checks see it."""

    def tree_hash(self) -> TreeSha: ...
    def changed_paths(self) -> list[str]: ...


class TreeWriter(Protocol):
    """The right to change the worktree's index: held by the check Fixer alone (tests/rules/test_tree_writer.py). A check reads the
    tree through CheckoutView and has no way to stage."""

    def stage_all(self, check: bool = ..., everything: bool = ...) -> int: ...


class WaitsView(Protocol):
    def note_slot_waits(self, text: str, wall: float) -> None: ...
    def start(self, what: WaitWhat, holder: str = ..., until: float | None = ..., lane: str = ..., check: str = ...) -> str: ...
    def add(self, secs: float, what: WaitWhat, wid: str | None = ..., lane: str = ..., check: str = ...) -> None: ...


class CheckHost(Protocol):
    """The Engine, as the checks see it."""

    @property
    def bead(self) -> str: ...
    @property
    def wt(self) -> str | Path: ...
    @property
    def run_id(self) -> str: ...  # the run's id: TL_RUN_ID in every check, `run_id` in every row
    @property
    def run_dir(self) -> Path: ...
    @property
    def home(self) -> ConfigDir: ...  # the config dir the run's rows live in
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def steps(self) -> CheckSteps: ...
    @property
    def checklog(self) -> CheckLog: ...
    @property
    def stores(self) -> Stores: ...
    @property
    def spawner(self) -> Spawner: ...  # how a check's helper processes are started
    @property
    def env(self) -> Env: ...  # the process environment, taken once at the edge: what the children are built from
    @property
    def killed(self) -> bool: ...  # the last sh() of this thread was stopped by the engine (an `in: linux` run sets it the same way)
    @killed.setter
    def killed(self, value: bool) -> None: ...
    @property
    def wall_hit(self) -> bool: ...  # ...at its wall limit
    @wall_hit.setter
    def wall_hit(self, value: bool) -> None: ...
    @property
    def bead_env(self) -> Mapping[str, str]: ...  # the slot's environment (sh() gives it to every command)

    def sh(self, cmd: Sequence[str], timeout: float = ..., check: bool = ..., save: Path | None = ..., env: Mapping[str, str] | None = ...,
           pin: bool = ..., what: str = ..., cwd: Path | None = ..., stop: threading.Event | None = ...) -> tuple[int, str]:
        """Run a command, an argv with no shell: (exit code, the last lines of its output). The whole output goes to `save`."""
        ...

    @property
    def checkout(self) -> CheckoutView: ...

    @property
    def tree_writer(self) -> TreeWriter: ...

    @property
    def git(self) -> Git: ...

    def warn(self, text: str) -> None: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...
    def detail(self, lines: list[str]) -> None: ...

    @property
    def waits(self) -> WaitsView: ...


class CleanHost:
    """The run's capabilities with a different checkout and command cwd; process flags still belong to the original host."""

    def __init__(self, host: CheckHost, wt: Path, checkout: CheckoutView) -> None:
        self.original, self.wt, self.checkout = host, wt, checkout
        self.bead, self.run_id, self.run_dir = host.bead, host.run_id, host.run_dir
        self.cfg, self.log, self.steps = host.cfg, host.log, host.steps
        self.checklog, self.stores = host.checklog, host.stores
        self.spawner, self.env, self.bead_env = host.spawner, host.env, host.bead_env
        self.git, self.waits = host.git, host.waits
        self.tree_writer = host.tree_writer
        self.warn, self.detail, self.halt_point = host.warn, host.detail, host.halt_point

    @property
    def killed(self) -> bool:
        return self.original.killed

    @killed.setter
    def killed(self, value: bool) -> None:
        self.original.killed = value

    @property
    def wall_hit(self) -> bool:
        return self.original.wall_hit

    @wall_hit.setter
    def wall_hit(self, value: bool) -> None:
        self.original.wall_hit = value

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None,
           stop: threading.Event | None = None) -> tuple[int, str]:
        return self.original.sh(cmd, timeout=timeout, check=check, save=save, env=env, pin=pin,
                                what=what, cwd=cwd or self.wt, stop=stop)
