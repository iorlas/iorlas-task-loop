"""Generation-bound session and result callbacks, retaining their identity across retries."""

from dataclasses import dataclass

from any_agent import RunOutcome

from taskloop.attempt import Attempts
from taskloop.attempt_types import Admission, CaptureResult, PendingResult
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.models import Outcome, Result
from taskloop.session import SessionLatch


@dataclass(frozen=True)
class PendingExecution:
    identity: Callback
    result: PendingResult


class Callbacks:
    def __init__(self, app: Attempts, admission: Admission, identity: Callback) -> None:
        if admission.key != identity.key:
            raise ValueError("Callback identity does not match admission")
        self.app, self.admission, self.identity = app, admission, identity
        self.sessions = SessionLatch(app.store, admission, identity)

    def observe(self, ref: str) -> Result:
        """The output hook retains latch state; direct consumers also receive an explained outcome."""
        self.sessions.observe(ref)
        state = self.sessions.snapshot()
        if state.fault is not None:
            return Result(outcome=Outcome.CHANGED, explanation="The execution's session callback was refused: " + state.fault)
        if state.conflict:
            return Result(outcome=Outcome.CONFLICT, explanation="A different session was reported; the saved session is retained.")
        if state.first_ref is not None:
            return Result(outcome=Outcome.UNAVAILABLE, explanation="The session report is retained pending available storage.")
        return Result(outcome=Outcome.ACCEPTED, explanation="The report matches the execution's saved session.")

    def returned(self, raw: RunOutcome) -> PendingExecution:
        return PendingExecution(self.identity, PendingResult(self.admission, raw, None, self.sessions.snapshot()))

    def capture(self, pending: PendingExecution) -> CaptureResult:
        identity, result = pending.identity, pending.result
        worker = result.raw.worker
        if (identity != self.identity or result.admission != self.admission or worker is None or
                (worker.pid, worker.pgid, worker.start, worker.boot) !=
                (identity.worker.pid, identity.worker.pgid, identity.worker.start, identity.worker.boot)):
            return CaptureResult("conflict", "worker_mismatch")
        return self.app.capture(result, identity)
