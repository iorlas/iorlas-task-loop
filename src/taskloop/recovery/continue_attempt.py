"""Continue one saved attempt under slot custody, reconciling before every launch."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from taskloop.attempt import Attempts
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import Admission, AttemptKey
from taskloop.drain.models import Identity
from taskloop.recovery.callbacks import Callbacks, PendingExecution
from taskloop.recovery.continuation_models import ContinuationResult, State, refused
from taskloop.recovery.execution_models import Phase
from taskloop.recovery.models import Intent, Outcome, ReconciliationState, Result
from taskloop.recovery.recover import Recovery
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable

type NativeExecution = Callable[[Admission, Intent], PendingExecution | Result]


class Continuation:
    def __init__(self, recovery: Recovery, attempts: Attempts, native: NativeExecution) -> None:
        self.recovery, self.attempts, self.native = recovery, attempts, native

    def __call__(
        self, key: AttemptKey, owner: Identity, *, custody: AbstractContextManager[None] | None = None,
    ) -> ContinuationResult:
        try:
            record = self.attempts.store.load(key)
            if record is None:
                return refused(Result(outcome=Outcome.INELIGIBLE, explanation="The saved attempt is absent."))
            with self.recovery.custody(record.admission) if custody is None else custody:
                return self._continue(record.admission, owner)
        except SlotBusy:
            return refused(Result(outcome=Outcome.CUSTODY_BUSY, explanation="Another operation holds the slot's custody."))
        except StoreRefused:
            return refused(Result(outcome=Outcome.INELIGIBLE, explanation="The saved attempt no longer has a valid reservation."))
        except (StoreUnavailable, SlotLockUnavailable):
            return ContinuationResult(state=State.UNAVAILABLE, explanation="Continuation storage or custody is unavailable.")

    def _continue(self, admission: Admission, owner: Identity) -> ContinuationResult:
        store, clock = self.recovery.store, self.recovery.clock
        snapshot = store.snapshot(admission.key, clock())
        if isinstance(snapshot, Result):
            return self._complete(admission) if snapshot.outcome is Outcome.CAPTURED else refused(snapshot)
        previous = snapshot.intent
        token = None
        if previous is not None:
            existing = self._existing(admission, previous)
            if existing is not None:
                return existing
            if previous.execution is not None and previous.execution.phase is Phase.REGISTERED:
                token = self.recovery.ids.hex()
        authorized = self.recovery.authorize(admission.key, owner, token=token, custody=nullcontext())
        if authorized.outcome is not Outcome.AUTHORIZED or authorized.intent is None:
            return refused(authorized)
        intended = store.execute(authorized.intent, clock)
        if intended.outcome is not Outcome.INTENDED or intended.intent is None:
            return refused(intended)
        returned = self.native(admission, intended.intent)
        return refused(returned) if isinstance(returned, Result) else self._capture(returned, intended.intent)

    def _existing(self, admission: Admission, previous: Intent) -> ContinuationResult | None:
        reconciled = self.recovery.reconcile(previous, custody=nullcontext())
        if isinstance(reconciled, Result):
            return refused(reconciled)
        if reconciled.state is ReconciliationState.CAPTURED:
            return self._complete(admission)
        if reconciled.state is ReconciliationState.LIVE:
            saved = None if reconciled.snapshot is None else reconciled.snapshot.intent
            return ContinuationResult(state=State.LIVE, explanation=reconciled.explanation, intent=saved)
        if reconciled.state is ReconciliationState.UNKNOWN:
            return refused(Result(outcome=Outcome.UNRESOLVED, explanation=reconciled.explanation, intent=previous))
        return None

    def capture(
        self, pending: PendingExecution, *, custody: AbstractContextManager[None] | None = None,
    ) -> ContinuationResult:
        """A returned result can only retry capture; this path has no execution effect."""
        try:
            with self.recovery.custody(pending.result.admission) if custody is None else custody:
                return self._capture(pending)
        except (SlotBusy, SlotLockUnavailable, StoreUnavailable):
            return ContinuationResult(state=State.PENDING_CAPTURE, explanation="Capture awaits storage or slot custody.", pending=pending)

    def _capture(self, pending: PendingExecution, intent: Intent | None = None) -> ContinuationResult:
        admission = pending.result.admission
        captured = Callbacks(self.attempts, admission, pending.identity).capture(pending)
        if captured.status == "unavailable":
            return ContinuationResult(state=State.PENDING_CAPTURE, explanation="The returned execution awaits durable capture.",
                                      intent=intent, pending=pending)
        if captured.status == "conflict":
            return refused(Result(outcome=Outcome.CONFLICT, explanation="The returned execution no longer owns capture authority."))
        return self._complete(admission)

    def _complete(self, admission: Admission) -> ContinuationResult:
        result = self.attempts.execute(admission.key, admission.entry)
        execution = result.execution
        decoded = execution is not None and execution.answer.kind != "validation_pending" and execution.session_state == "complete"
        state = State.COMPLETED if decoded else State.UNAVAILABLE
        return ContinuationResult(state=state, explanation="Captured execution was passed to trusted completion.", completion=result)
