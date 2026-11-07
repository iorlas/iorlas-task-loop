"""Stage capabilities consumed by the pipeline when a run closes."""
from collections.abc import Callable
from typing import Protocol

from taskloop.contracts import fence
from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.enums import Outcome
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import Park
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.lanes.pause_reasons import Producer


class AskRules(Protocol):
    def problems(self, spec: AskSpec) -> list[str]: ...


class ParkBook(Protocol):
    def paused(self, bead: Bead, kind: Kind, run: str, now: float, *, reason: str = "",
               not_before: float = 0.0, fingerprint: str = "", producer: Producer | None = None,
               permanence: Permanence | None = None) -> Park | None: ...

    def ended(self, bead: Bead, kind: Kind, run: str, now: float) -> None: ...


class FollowUps(Protocol):
    def file(self) -> list[dict[str, str]]: ...


class LandCleanup(Protocol):
    def retry(self, repo: str) -> None: ...


class BeadClosing(Protocol):
    def close(self, claim: fence.Claim, reason: str | None) -> int: ...

    def block(self, claim: fence.Claim, why: str, say: Callable[[str], None] | None = None) -> int: ...


class Slotting(Protocol):
    def leave_slot(self, outcome: Outcome, branch: str) -> None: ...
