"""Admit one repair after proving the failed execution stopped under slot custody."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from taskloop.answer_repair_models import RepairContext, RepairOutcome
from taskloop.answer_repair_store import AnswerRepairStore, RepairResult
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import Admission, AttemptKey
from taskloop.drain.models import Identity, Seen
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.ids import Ids
from taskloop.recovery.recover import Processes
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


class AnswerRepair:
    def __init__(
        self, store: AnswerRepairStore, files: EvidenceFiles, processes: Processes,
        hold: Callable[[Admission], AbstractContextManager[None]], clock: Callable[[], float], *, ids: Ids,
    ) -> None:
        self.store, self.files, self.processes = store, files, processes
        self.hold, self.clock, self.ids = hold, clock, ids

    def admit(self, previous: AttemptKey) -> RepairResult:
        try:
            existing = self.store.existing(previous)
            if existing is not None:
                return existing
            record = self.store.load(previous)
            if record is None:
                return RepairResult(outcome=RepairOutcome.REFUSED, explanation="The failed attempt is absent.")
            with self.hold(record.admission):
                return self._admit(previous)
        except SlotBusy:
            return RepairResult(outcome=RepairOutcome.UNAVAILABLE, explanation="Another operation holds the slot's custody.")
        except StoreRefused as error:
            return RepairResult(outcome=RepairOutcome.REFUSED, explanation=f"The failed attempt no longer owns repair admission: {error}.")
        except (StoreUnavailable, SlotLockUnavailable, EvidenceError, OSError, ValueError) as error:
            return RepairResult(outcome=RepairOutcome.UNAVAILABLE, explanation=f"Answer repair could not be saved: {error}.")

    def _admit(self, previous: AttemptKey) -> RepairResult:
        existing = self.store.existing(previous)
        if existing is not None:
            return existing
        record, execution = self.store.load(previous), self.store.collect(previous)
        if record is None or execution is None or record.worker is None or execution.answer.failure is None:
            return RepairResult(outcome=RepairOutcome.REFUSED,
                                explanation="A captured rejected answer with a registered worker is required.")
        if record.admission.repair is not None:
            return RepairResult(outcome=RepairOutcome.REFUSED, explanation="An answer repair cannot itself be repaired.")
        worker = record.worker
        entry = self.processes.entry(record.admission.entry)
        process = self.processes.process(Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot))
        if entry.seen is not Seen.GONE or process.seen is not Seen.GONE:
            return RepairResult(outcome=RepairOutcome.REFUSED,
                                explanation="Entry and worker absence must be confirmed. " + entry.explanation + " " + process.explanation)
        if record.session_ref is None or record.base_commit is None:
            return RepairResult(outcome=RepairOutcome.REFUSED, explanation="A saved session and execution base are required.")
        context = RepairContext(session=record.session_ref, base_commit=record.base_commit, failure=execution.answer.failure)
        key = AttemptKey(self.ids.hex(), self.ids.token(16), previous.reservation_generation + 1)
        text = ("Your previous answer broke this rule: " + context.failure.describe() + "\n"
                "Return a corrected answer in this same session, following the original task and answer contract. "
                "The existing work and original deadline are retained.\n")
        ref = self.files.put_input(key, text)
        return self.store.admit(record, execution, context, key, ref, self.clock())
