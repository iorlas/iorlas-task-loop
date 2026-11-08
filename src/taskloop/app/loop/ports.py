"""What the loop reads of the stages around it (slots, asks): small ports, so no loop module imports a stage. The adapters over the real
stages are stages.py; the composition root (launch/loop.py) builds them into the LoopEnv, a test builds fakes."""
from collections.abc import Callable
from typing import Protocol, Self

from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.ids import BeadId
from tlkernel.loop import Skip


class LeaseHandle(Protocol):
    def start(self) -> Self: ...
    def stop(self) -> None: ...
    def add(self, bead_id: BeadId) -> None: ...
    def drop(self, bead_id: BeadId) -> None: ...


class LoopSlots(Protocol):
    def ready_for(self, slot: str, bead: str) -> None:
        """A clean tree on the bead's branch in the slot, leftover work committed. SlotFail (code, why, setup) when it cannot."""

    def sets_up_at_base(self, slot: str) -> bool:
        """Whether the slot, detached at the base, passes its setup."""

    def mark_aside(self, name: str) -> None: ...
    def aside_recovered(self, source: str, claimed: str) -> bool:
        """Whether the slot set aside from `source` may be used again by a loop that claimed `claimed`."""

    def check_ready(self, name: str) -> None: ...
    def tick(self, *, ready_since: float | None, idle_loops: int) -> None:
        """The slot liveness invariants (at most every EVERY s)."""

    def wait_slot(self, why: str, *, stop: Callable[[], bool], sleep: Callable[[float], object], poll: tuple[float, float],
                  on_wait: Callable[[int], None], prio: int) -> tuple[str, str, BeadId] | None: ...
    def lease(self, store: Beads, slot_bead: BeadId | None, every: float) -> LeaseHandle: ...
    def release(self, name: str) -> None: ...
    def leaked(self) -> list[str]: ...
    def release_leaked(self, name: str) -> None: ...
    def worktree_path(self, repo: str, name: str) -> str: ...


class LoopAsks(Protocol):
    def held(self, b: Bead) -> bool:
        """The bead is parked, held or waiting for an answer: not to be taken now."""

    def skip_of(self, b: Bead) -> Skip | None:
        """The queue's typed skip for the park gate (None when the bead may be taken)."""

    def profile_ahead(self, b: Bead, run: str, why: str) -> None:
        """Park the bead for a short, random time: its profile is ahead of this checkout, or its setup is on its own tree."""

    def promote_if_due(self, store: Beads, per_day: int, now: float, last: float, say: Callable[[str], object]) -> float: ...
