"""The land phase of a round (tl-8bh9.14.136): under the profile's `land: auto` the round lands the oldest passed task in
the selected repository and backlog, including hand-started tasks, through `land.land`, the very operation `tl step land`
runs (no second path). At most one task is landed or held per
round; the land's own lock and the free-slot reserve for it (`round._full`) still apply.

Each outcome is one move of the round log. Landed: the task is closed and its claim returned (the land's close). A refusal
about the task's own change (`HOLDING`: it conflicts with `main`, S's checks failed, the remote's policy refused the push,
the branch moved, the claim is lost) holds the task with the cause `land:<reason>` (`hold.hold_task`; its comment says what
a person can do): a held task is `on_hold`, so the refusal is recorded once and never tried again until the person answers.
An unknown (`unavailable:*`) is tried again next round (a rerun is safe). Any other refusal (`gate_changed` and `no_change`,
which only a person accepts, `push_barred`, `landing`, ...) is only reported (once in the log while unchanged), leaves the
task waiting and does not stop the next one. Under `manual`, or without the port, nothing is read or landed here.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from taskloop.attempt_status import AttemptView
from taskloop.hold_cause import LAND_CAUSE
from taskloop.land import How, LandRequest
from taskloop.operations import Failed, Move
from taskloop.profile import LandMode
from taskloop.round_trail import Trail
from taskloop.task_status import waiting_for_land

# the refusals that are about the task's change: hold it instead of trying again every round
HOLDING: Final = frozenset({"conflict", "checks_failed", "remote_rejected", "branch_moved", "claim_lost"})


@dataclass(frozen=True)
class Landing:
    """`mode`: the profile's `land` at origin's `main` as fetched now, for the checkout; `land`: one `land.land`."""

    mode: Callable[[Path], LandMode | Failed]
    land: Callable[[LandRequest], How | Failed]


def _waiting(current: Iterable[AttemptView]) -> list[AttemptView]:
    """The tasks whose checks passed and wait for a land, the oldest release first."""
    found = [each for each in current if waiting_for_land(each)]
    return sorted(found, key=lambda each: (each.checks.row.released_at or 0.0 if each.checks else 0.0, each.task_id))


def land_passed(landing: Landing | None, backlog: str, checkout: Path, minutes: int, current: Iterable[AttemptView], trail: Trail,
                hold: Callable[[AttemptView, str], Move]) -> frozenset[str]:
    """The tasks this phase finished (landed or held): the free-slot reserve for a waiting land no longer counts them."""
    waiting = _waiting(current)
    if landing is None or not waiting:
        return frozenset()
    mode = landing.mode(checkout)
    if isinstance(mode, Failed):
        first = waiting[0]
        trail.add(Move(first.task_id, "land", mode.word, first.attempt_id, mode.detail, first.step))
        return frozenset()
    if mode is not LandMode.AUTO:
        return frozenset()
    for each in waiting:
        found = landing.land(LandRequest(backlog, each.task_id, checkout, minutes))
        if not isinstance(found, Failed):
            trail.add(Move(each.task_id, "land", found, each.attempt_id, step=each.step))
            return frozenset({each.task_id})
        if found.kind == "refused" and found.reason in HOLDING:
            trail.add(hold(each, f"{LAND_CAUSE}{found.reason}"))
            return frozenset({each.task_id})
        trail.add(Move(each.task_id, "land", found.word, each.attempt_id, found.detail, each.step))
        if found.kind != "refused":
            break
    return frozenset()
