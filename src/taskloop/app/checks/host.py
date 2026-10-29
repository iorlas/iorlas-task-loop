"""What the checks need of the engine that runs them, and the two ways a round stops the run."""
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from taskloop.app.checks.checklog import CheckLog
from taskloop.contracts.checks import CheckFaultKind
from taskloop.contracts.config import EngineConfig
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class CheckFault(Exception):
    """A check ended the run's step: the engine turns it into a Blocked of the matching kind."""

    def __init__(self, kind: CheckFaultKind, text: str) -> None:
        super().__init__(text)
        self.kind = kind
        self.text = text


class CheckStuck(Exception):
    """The same checks were red with the same output in `rounds` rounds in a row: more writes will not fix it. `signature` names them."""

    def __init__(self, signature: str, rounds: int) -> None:
        super().__init__(signature)
        self.signature = signature
        self.rounds = rounds


class CheckSteps(Protocol):
    """The run's step book, as the checks use it."""

    id: str

    def begin(self, kind: str, title: str, **meta: object) -> object: ...
    def outcome(self, word: str, text: str) -> object: ...


class CheckoutView(Protocol):
    """The slot's checkout (app/land/checkout.py), as the checks see it."""

    def tree_hash(self) -> str: ...
    def git_env(self) -> Mapping[str, str]: ...
    def changed_paths(self) -> list[str]: ...
    def stage_all(self, check: bool = ..., everything: bool = ...) -> int: ...


class WaitsView(Protocol):
    def note_slot_waits(self, text: str, wall: float) -> None: ...
    def start(self, what: str) -> str: ...
    def add(self, secs: float, what: str, wid: str | None = ...) -> None: ...


class CheckHost(Protocol):
    """The Engine, as the checks see it."""

    bead: str
    wt: str | Path
    run_dir: Path
    cfg: EngineConfig
    log: RunLog
    steps: CheckSteps
    checklog: CheckLog
    stores: Stores
    killed: bool  # the last sh() was stopped by the engine
    wall_hit: bool  # the last sh() was stopped at its wall limit
    bead_env: Mapping[str, str]  # the slot's environment (sh() gives it to every command)

    def sh(self, cmd: Sequence[str], timeout: float = ..., check: bool = ..., save: Path | None = ..., env: Mapping[str, str] | None = ...,
           pin: bool = ..., what: str = ..., cwd: Path | None = ...) -> tuple[int, str]:
        """Run a command, an argv with no shell: (exit code, the last lines of its output). The whole output goes to `save`."""
        ...

    @property
    def checkout(self) -> CheckoutView: ...

    def git(self, *args: str) -> str: ...
    def warn(self, text: str) -> None: ...
    def detail(self, lines: list[str]) -> None: ...

    @property
    def waits(self) -> WaitsView: ...
