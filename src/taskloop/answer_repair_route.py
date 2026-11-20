"""Route rejected answers through their one durable same-session repair before terminal handling."""

from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from taskloop.answer_repair_models import RepairOutcome
from taskloop.answer_repair_store import RepairResult
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_result import report
from taskloop.attempt_status import AttemptView
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.hold_store import HoldStore
from taskloop.operations import Failed, Launch, Move, Started, StartPorts, launched


class RepairReason(StrEnum):
    ADMISSION = "answer_repair"


def repair_move(ports: StartPorts, backlog: str, minutes: int, view: AttemptView) -> Move | None:
    """Try repair before a round settles its terminal snapshot; current-attempt fences protect successors."""
    if (
        view.next not in {"hold", "release", "done", "repeat"}
        or view.checks is not None
        or view.hold is not None
        or view.release is not None
        or ports.answer_repair is None
    ):
        return None
    try:
        current = ports.reader.attempt_of(backlog, view.task_id)
        result = (
            Failed("refused", "changed", "Another attempt is current since this round read the store.")
            if current is None or current[0].attempt_id != view.attempt_id
            else ports.answer_repair.route(backlog, view.task_id, current[0], minutes)
        )
    except StoreUnavailable as error:
        result = Failed("unavailable", "store", str(error))
    if result is None or (isinstance(result, Failed) and result.kind == "not_applicable"):
        return None
    if isinstance(result, Started):
        return Move(view.task_id, "repeat", result.status, result.attempt_id, step=view.step)
    return Move(view.task_id, "repeat", result.word, view.attempt_id, result.detail, view.step)


class RepairAdmission(Protocol):
    def admit(self, previous: AttemptKey) -> RepairResult: ...


class AnswerRepairRouting:
    def __init__(self, reader: AttemptStore, admission: RepairAdmission, launcher: Launch) -> None:
        self.reader, self.admission, self.launcher = reader, admission, launcher

    def route(self, backlog: str, task_id: str, previous: AttemptKey, minutes: int) -> Started | Failed | None:
        """None leaves ordinary execution handling alone; not_applicable allows the round's terminal handling.

        Every other result defers terminal effects, including a saved successor whose launch failed.
        Admission and dispatch retain their own transactional fences and duplicate-dispatch protection.
        """
        try:
            return self._route(backlog, task_id, previous, minutes)
        except StoreUnavailable as error:
            return Failed("unavailable", "store", str(error))

    def _current(self, backlog: str, task_id: str, previous: AttemptKey) -> Failed | None:
        current = self.reader.attempt_of(backlog, task_id)
        if current is None or current[0] != previous:
            return Failed("refused", "changed", "Another attempt is current since the answer was read.")
        held = HoldStore(self.reader.connect, self.reader.begin).of_attempts((previous.attempt_id,))
        if held or self.reader.release_of(previous) is not None:
            return Failed("refused", "changed", "The attempt is already held or released.")
        return None

    def _route(self, backlog: str, task_id: str, previous: AttemptKey, minutes: int) -> Started | Failed | None:
        execution = self.reader.collect(previous)
        if (
            execution is None
            or execution.answer.failure is None
            or execution.facts.rc != 0
            or execution.facts.timed_out
            or execution.facts.stop is not None
            or execution.session_state != "complete"
            or execution.verdict is not None
        ):
            return None
        try:
            record = self.reader.load(previous)
        except StoreRefused:  # a saved successor owns the reservation; admission can adopt it
            record = None
        if record is not None and record.session_conflict:
            return None
        result = report(execution)
        if record is not None and record.admission.repair is not None:
            return self._current(backlog, task_id, previous) or Failed("not_applicable", result.reason, result.explanation)
        repair = self.admission.admit(previous)
        if repair.outcome is RepairOutcome.UNAVAILABLE:
            return Failed("unavailable", RepairReason.ADMISSION, repair.explanation)
        if repair.outcome is RepairOutcome.REFUSED or repair.key is None:
            return self._current(backlog, task_id, previous) or Failed(
                "not_applicable", result.reason, result.explanation + " " + repair.explanation
            )
        return self._launch(backlog, task_id, repair.key, minutes, existing=repair.outcome is RepairOutcome.EXISTING)

    def _launch(self, backlog: str, task_id: str, key: AttemptKey, minutes: int, *, existing: bool) -> Started | Failed:
        if changed := self._current(backlog, task_id, key):
            return changed
        launched_result = launched(self.launcher.launch(backlog, task_id, minutes), backlog, task_id, key, existing=existing)
        return replace(launched_result, admitted=True) if isinstance(launched_result, Failed) else launched_result
