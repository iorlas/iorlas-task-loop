"""Gates in flight (docs/design/merge-queue.md section 6, terms in docs/glossary.md): how many PRs of the merge queue are tested at the
same time. It starts at the floor, 1 (today's serial landing), grows by 1 after each merged PR, halves after the queue's own gate failure
or a conflict eject, and stays between the floor and the cap. A flake or an infra stop says nothing about the speculation, so it never
shrinks it. A wasted ratio above WASTE_HOLD over the last WASTE_WINDOW merges holds the growth."""
from collections.abc import Iterable
from enum import StrEnum
from typing import Final, final

from taskloop.contracts.wire import Rec

FLOOR: Final = 1
DEFAULT_CAP: Final = 4  # land-stack's --jobs default; the config key `land.queue.max_in_flight` will carry it
WASTE_WINDOW: Final = 20  # merges the wasted ratio looks back over
WASTE_HOLD: Final = 0.5  # a guess, tunable (design section 6)


class Event(StrEnum):
    MERGED = "merged"
    GATE_FAILED = "gate_failed"  # the queue's own gate for a PR went red
    CONFLICT_EJECT = "conflict_eject"  # a PR did not merge into the queue ahead of it
    FLAKE = "flake"  # a red the flake policy retries: no information about the speculation
    INFRA = "infra"  # a gate that could not run


class Cause(StrEnum):
    CULPRIT_AHEAD = "culprit_ahead"
    BASE_MOVED = "base_moved"
    HEAD_CHANGED = "head_changed"
    CONFIG_CHANGE = "config_change"


@final
class Account(Rec):
    """The gate seconds one merge cost: useful_gate_s: gates whose result was used, wasted_gate_s: gates cancelled or invalidated since the
    merge before it, each with the cause of its waste."""

    pr: int
    useful_gate_s: float
    wasted_gate_s: float = 0.0
    causes: tuple[Cause, ...] = ()

    def __post_init__(self) -> None:
        if self.wasted_gate_s and not self.causes:
            raise ValueError("wasted gate seconds need a cause")


def wasted_ratio(accounts: Iterable[Account]) -> float:
    """wasted / (wasted + useful) over the newest WASTE_WINDOW accounts; 0 when nothing ran."""
    last = list(accounts)[-WASTE_WINDOW:]
    wasted, useful = sum(a.wasted_gate_s for a in last), sum(a.useful_gate_s for a in last)
    return wasted / (wasted + useful) if wasted + useful else 0.0


def in_flight(current: int, event: Event, *, cap: int = DEFAULT_CAP, ratio: float = 0.0) -> int:
    """The gates in flight after `event`: +1 on a merge unless the wasted `ratio` holds it, halved (rounded down) on a gate failure or a
    conflict eject, unchanged on a flake or an infra stop; always between FLOOR and `cap`."""
    cap = max(FLOOR, cap)
    if event is Event.MERGED:
        current += 0 if ratio > WASTE_HOLD else 1
    elif event in (Event.GATE_FAILED, Event.CONFLICT_EJECT):
        current //= 2
    return min(cap, max(FLOOR, current))
