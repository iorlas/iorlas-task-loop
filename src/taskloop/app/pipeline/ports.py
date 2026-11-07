"""Stage capabilities consumed by the pipeline when a run closes."""
from collections.abc import Callable, Sequence
from typing import Protocol

from tlkernel import fence
from tlkernel.bead import Bead
from tlkernel.delegate import Permanence
from tlkernel.enums import Outcome
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import Park
from tlkernel.review import ReviewState
from tlkernel.run import NetPause, ReexecNote

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


class TrustRefusal(Protocol):
    def refusal(self, git: Git, wt: str, base: str, bead: Bead | None) -> str: ...


class HeadHistory(Protocol):
    def since(self, wt: str, head: str, n: int) -> str: ...


class ReviewRestore(Protocol):
    def apply(self, review: ReviewState, *, unchecked: bool, late: bool = False) -> None: ...


class Reexecs(Protocol):
    def net_pause(self, pause: NetPause) -> None: ...
    def note(self, note: ReexecNote) -> None: ...
    def args(self, argv: Sequence[str], slot: str, wt: str) -> list[str] | None: ...
    def drop(self, bead: BeadId) -> None: ...
    def exec(self, argv: list[str], env: dict[str, str]) -> None: ...


class Trail(Protocol):
    def event(self, by: Identity, kind: str, bead: str, **fields: str) -> None: ...
