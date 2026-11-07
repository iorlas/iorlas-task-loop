"""The small seams: the clock, the shell, the owner's answer and delegate. The big ones: gitport, beadsport, checksport, procport."""
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from tlkernel.ask import Ask, AskAction
from tlkernel.delegate import DelegateResult, LiveEvent, RunRequest
from tlkernel.ids import BeadId

EventSink = Callable[[LiveEvent], None]


class Clock(Protocol):
    """Time, as a capability: SystemClock (adapters/clock.py) in production, FakeClock in tests."""

    def now(self) -> float: ...
    def monotonic(self) -> float: ...


class Sh(Protocol):
    """The engine's one way to run a command (an argv, no shell): (exit code, the last lines of its output).
    Git pushes return complete output; the whole output of any command goes to `save`."""

    def __call__(self, cmd: Sequence[str], timeout: float = ..., check: bool = ..., save: Path | None = ...,
                 env: Mapping[str, str] | None = ..., pin: bool = ..., what: str = ..., cwd: Path | None = ...) -> tuple[int, str]: ...


class AnswerAsk(Protocol):
    """The owner's answer to an ask: the one intake `tl answer` uses (typed record, bead opened, receipt comment). The dashboard calls
    it with the ask's repo and bead, and `expect`, the id of the ask the owner saw (a newer ask refuses it: superseded);
    -> (the ask, "" or why: answered, withdrawn, closed, consumed, superseded, gone)."""

    def __call__(self, repo: str, bead: BeadId, action: AskAction, text: str, amend: bool, expect: str = "") -> tuple[Ask | None, str]: ...


class Delegate(Protocol):
    def speaks(self) -> int:
        """The contract number delegate answers with (`route.py contract --json`); the caller gates on 4."""
        ...

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        """One AI step. `brief` and `schema` travel as values (an adapter that needs files makes them; `req.brief_path` and
        `req.schema_path` are ignored here). Never raises for a worker's failure: that is a result with `stop` set.
        `on_event` gets the worker's live events, in order, before `run` returns."""
        ...
