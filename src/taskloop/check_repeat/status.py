"""The shared, read-only decision for check-driven implement repeats."""

from dataclasses import dataclass
from enum import StrEnum

from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import ATTEMPTS, AttemptKey
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.land_store import LandStore


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
    if any(each.conclusion not in ("passed", "failed") or each.ended_at is None for each in results):
        return None
    by_name = {each.name: each for each in results}
    if any(name not in by_name for name, _ in row.required):
        return None
    first = next((by_name[name] for name, _ in row.required if by_name[name].conclusion != "passed"), None)
    if first is None or first.rc in (None, 0) or first.conclusion != "failed":
        return None
    return first if row.reason == f"{first.name}:{first.conclusion}" else None


def decision(number: int, row: ChecksRow, results: tuple[ResultRow, ...], *, blocked: bool = False) -> CheckRepeatDecision:
    if blocked or failed_result(row, results) is None:
        return CheckRepeatDecision.INELIGIBLE
    if number >= ATTEMPTS:
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
    outcome = decision(rows[0].number, row, CheckStore(reader.connect, reader.begin).results(row.key), blocked=blocked)
    return CheckRepeatTarget(previous, row.key) if outcome is CheckRepeatDecision.REPEAT else outcome
