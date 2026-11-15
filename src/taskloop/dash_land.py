"""Pending delivery details through the same summary operation as the land command."""

from pathlib import Path

from taskloop.attempt_types import Observe
from taskloop.check_store import ChecksRow
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.dash_model import LandDetail, LandEvent, LandEventKind, LandWait, iso
from taskloop.land import LandRequest, land
from taskloop.land_check import LandPorts
from taskloop.land_store import LandRow, LandStore
from taskloop.land_summary import LandSummary
from taskloop.operations import Failed


def _actions(found: LandSummary) -> tuple[str, ...]:
    if found.state == "conflict":
        return ("Delivery is blocked by conflicts; resolve the task's changes before integration.",)
    if found.conclusion != "passed":
        return ("Delivery is blocked until the task's checks pass.",)
    if found.state == "no_change":
        return ("Record that main already contains the task's changes and mark the task complete.",)
    return (
        *(("Validate the changes against current main with the required checks.",) if found.again else ()),
        *(("The changes to the check gate require your acceptance before delivery.",)
          if found.gate is not None and found.gate.decisive else ()),
        "Integrate the task's changes into main on origin.",
        "Mark the task complete.",
    )


def build_land(ports: LandPorts, backlog: str, task_id: str, checkout: Path) -> LandDetail | Failed:
    """Summary only: may fetch and create Git objects, but never validate, deliver, close or claim."""
    found = land(ports, LandRequest(backlog, task_id, checkout, None, "summary"))
    if isinstance(found, Failed):
        return found
    if not isinstance(found, LandSummary):
        return Failed("unavailable", "land", "The delivery summary could not be read.")
    changes = None if found.gate is None else found.gate.changes
    return LandDetail(
        actions=_actions(found), summary=_summary(found),
        diff_files=None if changes is None else len(changes),
        added=None if changes is None else sum(each.added for each in changes),
        deleted=None if changes is None else sum(each.deleted for each in changes),
    )


def _summary(found: LandSummary) -> tuple[str, ...]:
    gate = found.gate
    return (
        f"Checks: {found.checks_id}; {found.conclusion or 'unfinished'}.",
        *(f"Check {name}: {encode(result) if isinstance(result, CommandConclusion) else result}." for name, result in found.results),
        f"Checked commit: {found.x}. Main before checks: {found.target}. Origin main: {found.origin}.",
        *(f"Required check added: {name}." for name in found.added),
        *(f"Required check removed: {name}." for name in found.removed),
        *(f"Check configuration changed: {each.name}." for each in found.argv),
        *(() if gate is None else (
            *(f"{each.path} +{each.added} -{each.deleted}" for each in gate.changes),
            *(f"Check definition changed: {each.name}." for each in gate.checks),
            *(("Setup configuration changed.",) if gate.setup is not None else ()),
            *((f"Required checks changed: {', '.join(gate.required[0])} → {', '.join(gate.required[1])}.",)
              if gate.required is not None else ()),
            *(f"Configuration changed: {path}." for path in gate.configs),
            *(f"Test weakened: {each.path}: {each.why}" for each in gate.weakened),
        )),
        *(f"Conflict: {path}." for path in found.conflicts),
    )


def _latest(*times: float | None) -> float | None:
    return None if any(time is None for time in times) else max(time for time in times if time is not None)


def _wait(after: str, start: float | None, end: float | None, opened: bool, awaited: str) -> LandWait:
    if start is not None and end is not None and end < start:
        start = end = None
    return LandWait(after=after, started_at=iso(start), ended_at=iso(end), open=opened, awaited=awaited)


def _waits(row: LandRow, event_id: str, opened: bool, observe: Observe) -> tuple[LandWait, ...]:
    if row.pending:
        if row.entry is not None and observe(row.entry) == "matching":
            return ()
        return (_wait(event_id, None, None, opened, "Waiting for the validation process to be reconciled; activity is unconfirmed."),)
    waits: list[LandWait] = []
    finished = row.validated_at if row.validation is not None else row.superseded_at
    if row.slot is not None:
        waits.append(_wait(event_id, finished, row.released_at, opened and row.holds_slot,
                           "Waiting for the validation slot to be released."))
    start = finished if row.slot is None else _latest(finished, row.released_at)
    if not row.holds_slot and row.validation is not None and row.validation != "failed":
        end = row.delivered_at if row.delivery is not None else row.superseded_at
        waits.append(_wait(event_id, start, end, opened and row.delivery is None and row.superseded is None,
                           "Waiting for integration into main."))
    if row.delivery is not None:
        waits.append(_wait(event_id, row.delivered_at, row.closed_at, opened and row.close is None,
                           "Waiting for confirmed task completion."))
    if not row.holds_slot and (row.validation == "failed" or row.superseded is not None):
        start = _latest(start, row.superseded_at) if row.superseded is not None else start
        waits.append(_wait(event_id, start, None, opened, "Waiting for another delivery try or a decision about the task."))
    return tuple(waits)


def _candidate(row: LandRow, checks: ChecksRow, number: int, past: bool, opened: bool, observe: Observe) -> tuple[LandEvent, ...]:
    event_id = f"{row.key.attempt_id}/tried"
    explanation = f"Delivery candidate {row.number}: {row.validation or 'validation unfinished'}."
    if row.superseded is not None:
        explanation += f" Superseded: {row.superseded}."
    if row.reason:
        explanation += f" {row.reason}"
    tried = LandEvent(id=event_id, kind=LandEventKind.TRIED, checks_id=checks.key.attempt_id, checks_n=number,
                      candidate_id=row.key.attempt_id, candidate_n=row.number, at=None, past=past,
                      explanation=explanation, waits=_waits(row, event_id, opened, observe))
    if row.delivery is None or row.close is None or row.holds_slot:
        return (tried,)
    at = _latest(row.delivered_at, row.closed_at, *(() if row.slot is None else (row.released_at,)))
    return (tried, LandEvent(id=f"{row.key.attempt_id}/landed", kind=LandEventKind.LANDED,
                            checks_id=checks.key.attempt_id, checks_n=number, candidate_id=row.key.attempt_id,
                            candidate_n=row.number, at=iso(at), past=past,
                            explanation="Integrated into main, task completion confirmed and any validation slot released."))


def build_events(store: LandStore, checks: tuple[tuple[ChecksRow, int, bool], ...], observe: Observe) -> tuple[LandEvent, ...]:
    """Project owning rows in checks-chain order. Reading history never invokes land."""
    events: list[LandEvent] = []
    for position, (checked, number, historical) in enumerate(checks):
        if checked.conclusion != "passed" or checked.released_at is None:
            continue
        past = historical or checked.abandoned
        current = not past and position == len(checks) - 1
        candidates = store.of_checks(checked.key.attempt_id)
        event_id = f"{checked.key.attempt_id}/ready"
        at = _latest(checked.concluded_at, checked.released_at)
        events.append(LandEvent(id=event_id, kind=LandEventKind.READY, checks_id=checked.key.attempt_id,
                                checks_n=number, at=iso(at), past=past,
                                explanation="Checks passed and their slot was released; ready for delivery.",
                                waits=(_wait(event_id, at, None, not candidates and current,
                                             "Waiting for a delivery try."),)))
        for index, row in enumerate(candidates):
            events.extend(_candidate(row, checked, number, past, current and index == len(candidates) - 1, observe))
    return tuple(events)
