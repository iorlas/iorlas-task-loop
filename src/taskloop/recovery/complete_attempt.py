"""Finish already captured work under slot custody, without authorizing execution."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from taskloop.attempt import Attempts
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import Admission, AttemptRecord, AttemptResult, Observe
from taskloop.hold_store import HoldStore
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


class CapturedCompletion:
    def __init__(
        self, attempts: Attempts, holds: HoldStore, custody: Callable[[Admission], AbstractContextManager[None]], observe: Observe,
    ) -> None:
        self.attempts, self.holds, self.custody, self.observe = attempts, holds, custody, observe

    def __call__(self, backlog: str, task_id: str, attempt_id: str) -> AttemptResult:
        store = self.attempts.store
        try:
            found = store.attempt_of(backlog, task_id)
            if found is None or found[0].attempt_id != attempt_id:
                return AttemptResult("refused", "changed")
            record = store.load(found[0])
            if record is None:
                return AttemptResult("refused", "absent")
            with self.custody(record.admission):
                return self._complete(record)
        except (StoreUnavailable, SlotBusy, SlotLockUnavailable):
            return AttemptResult("unavailable", "store")
        except StoreRefused as error:
            return AttemptResult("refused", str(error))

    def _complete(self, record: AttemptRecord) -> AttemptResult:
        store, admission = self.attempts.store, record.admission
        key = admission.key
        current = store.attempt_of(admission.task.scope.backlog, admission.task.task_id)
        if (current is None or current[0] != key or store.load(key) != record or store.release_of(key) is not None
                or self.holds.held(key.attempt_id)):
            return AttemptResult("refused", "changed")
        if self.observe(admission.entry) not in ("gone", "different_process"):
            return AttemptResult("pending", "entry")
        captured = store.collect(key)
        if captured is None:
            return AttemptResult("refused", "absent")
        if record.session_conflict or captured.session_state == "conflict":
            return AttemptResult("conflict", "session", captured)
        return self.attempts.execute(key, admission.entry)
