"""The members of the engine that more than one land step reads, each as a Protocol of just what is called (a step's host lists the parts
it needs and nothing else)."""
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from taskloop.contracts.plancheck import PlanCheck


class BeginSteps(Protocol):
    def begin(self, step: str, text: str, **meta: object) -> int: ...


class OutcomeSteps(Protocol):
    def outcome(self, outcome: str, detail: str = ...) -> None: ...


class MoveSteps(Protocol):
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...


class OutcomeMoveSteps(OutcomeSteps, MoveSteps, Protocol):
    pass


class FetchCheckout(Protocol):
    def fetch(self, check: bool = ...) -> tuple[int, str]: ...


class StageCheckout(Protocol):
    def stage_all(self, check: bool = ..., everything: bool = ...) -> int: ...


class Strays(Protocol):
    def quarantine_strays(self) -> list[str]: ...


class Net(Protocol):
    def net_up(self) -> bool | None: ...
    def await_net(self, up: bool | None, max_s: float) -> tuple[float, bool]: ...


class NetWorker(Protocol):
    @property
    def acts(self) -> Net: ...


class LandLocks(Protocol):
    def locked(self, what: str, path: Path | str, holder: str | None = ...) -> AbstractContextManager[Path | str]: ...


class CaseChecks(Protocol):
    def case_checks(self) -> Sequence[PlanCheck]: ...
