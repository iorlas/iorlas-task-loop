"""The shared, read-only decision for check-driven implement repeats."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from taskloop.admit_store import stored_pin
from taskloop.attempt_reads import StoreConnection, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.land_store import LandStore
from taskloop.step import Step
from taskloop.workflow_read import WorkflowRefusal


class CheckRepeatDecision(StrEnum):
    INELIGIBLE = "ineligible"
    RELEASE = "release"
    REPEAT = "repeat"
    EXHAUSTED = "exhausted"


def failed_result(row: ChecksRow, results: tuple[ResultRow, ...]) -> ResultRow | None:
    """Required order, never display order. A command that failed to exec has no nonzero rc and cannot qualify.
    Require a completed ordinary block; infrastructure conclusions, including an optional dirty result, retain ownership.
    The attempt's cause must agree with the structured result (expired/profile/main-moved take precedence)."""
    if row.phase != "concluded" or row.conclusion != "failed" or row.abandoned or not results:
        return None
    if any(each.conclusion not in (CommandConclusion.PASSED, CommandConclusion.FAILED) or each.ended_at is None for each in results):
        return None
    by_name = {each.name: each for each in results}
    if any(name not in by_name for name, _ in row.required):
        return None
    first = next((by_name[name] for name, _ in row.required if by_name[name].conclusion is not CommandConclusion.PASSED), None)
    if first is None or first.rc in (None, 0) or first.conclusion != CommandConclusion.FAILED:
        return None
    return first if row.reason == f"{first.name}:{encode(first.conclusion)}" else None


class CapStore(StoreConnection):
    def of(self, attempt_id: str, step: Step) -> int:
        """How many attempts `step` may take: the attempt's pinned workflow's, read when asked (the one owner of the cap)."""
        with self._connection() as con:
            try:
                return stored_pin(con, attempt_id).workflow.cap(step)
            except WorkflowRefusal:
                raise StoreUnavailable("The stored workflow no longer loads") from None


def decision(
    number: int, cap: Callable[[], int], row: ChecksRow, results: tuple[ResultRow, ...], *, blocked: bool = False
) -> CheckRepeatDecision:
    if blocked or failed_result(row, results) is None:
        return CheckRepeatDecision.INELIGIBLE
    if number >= cap():
        return CheckRepeatDecision.EXHAUSTED
    return CheckRepeatDecision.RELEASE if row.released_at is None else CheckRepeatDecision.REPEAT


@dataclass(frozen=True)
class CheckRepeatTarget:
    previous: AttemptKey
    source: AttemptKey


def repeat_target(reader: AttemptStore, previous: AttemptKey, row: ChecksRow | None) -> CheckRepeatTarget | CheckRepeatDecision:
    if row is None:
        return CheckRepeatDecision.INELIGIBLE
    rows = reader.attempts(row.backlog, row.task_id)
    if not rows or rows[0].key != previous:
        return CheckRepeatDecision.INELIGIBLE
    land = LandStore(reader.connect, reader.begin).latest(row.key.attempt_id)
    blocked = land is not None and (land.delivery is not None or land.holds_slot or land.pushable)
    results = CheckStore(reader.connect, reader.begin).results(row.key)
    cap = CapStore(reader.connect, reader.begin)
    outcome = decision(rows[0].number, lambda: cap.of(previous.attempt_id, Step.IMPLEMENT), row, results, blocked=blocked)
    return CheckRepeatTarget(previous, row.key) if outcome is CheckRepeatDecision.REPEAT else outcome
