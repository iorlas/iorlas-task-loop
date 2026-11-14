"""Commit a stop intent before the supervisor acts, then its report even when execution exits exceptionally.

The supervisor owns serialization and the action. A failed callback propagates: no unrecorded stop and no cleanup retry.
Recovery only reads these facts; neither an intent nor a missing report authorizes another stop.
"""

from collections.abc import Callable

from any_agent import StopIntent
from any_agent.procs import StopReport, Worker

from taskloop.agents.stop_models import AgentStop, Identity, StopCause, StopProof, Survivor
from taskloop.agents.stop_store import StopStore
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import Admission, AttemptKey, WorkerGone


def reconcile(store: StopStore, key: AttemptKey, gone: WorkerGone, now: float) -> bool:
    """Observe only. A live or unknown target keeps its intent unresolved and its reservation held by release's proof."""
    record = store.get(key.attempt_id)
    if record is None:
        return True
    if (record.dispatch_token, record.generation) != (key.dispatch_token, key.reservation_generation):
        raise StoreRefused("changed")
    if not gone(owned_worker(record)):
        return False
    if record.proof is not None:
        for survivor in record.proof.survivors:
            if survivor.start is None or not gone(Worker(pid=survivor.pid, pgid=record.agent.pgid,
                                                        start=survivor.start, boot=record.agent.boot)):
                return False
    store.observed_gone(record, now)
    return True


def owned_worker(record: AgentStop) -> Worker:
    agent = record.agent
    return Worker(pid=agent.pid, pgid=agent.pgid, start=agent.start, boot=agent.boot)

_CAUSES = {
    "timeout": StopCause.DEADLINE, "secret": StopCause.POLICY, "answer": StopCause.ANSWER,
    "hung:first_event": StopCause.FIRST_OUTPUT, "hung:silence": StopCause.INACTIVITY, "hung:stall": StopCause.STALLED,
    "stall": StopCause.STALLED, "limit": StopCause.LIMIT, "credit": StopCause.CREDIT,
    "logged_out": StopCause.AUTHENTICATION, "network": StopCause.NETWORK, "watchdog": StopCause.WATCHDOG,
    "entry_signal": StopCause.ENTRY_SIGNAL, "interrupt": StopCause.INTERRUPT,
    "parent_gone": StopCause.PARENT_LOST, "caller": StopCause.CALLER_EXIT,
}


class AgentStops:
    def __init__(self, store: StopStore, admission: Admission, clock: Callable[[], float]) -> None:
        self.store, self.admission, self.clock = store, admission, clock
        self.intent: AgentStop | None = None

    def _record(self, intent: StopIntent, now: float) -> AgentStop:
        admission, worker = self.admission, intent.worker
        reason = _CAUSES[intent.reason]
        return AgentStop(
            attempt_id=admission.key.attempt_id, dispatch_token=admission.key.dispatch_token,
            generation=admission.key.reservation_generation,
            entry=Identity(pid=admission.entry[0], pgid=admission.entry[0], start=admission.entry[1], boot=admission.entry[2]),
            agent=Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot), cause=reason,
            requested_signal=intent.first_signal, trigger_signal=intent.trigger_signal, requested_at=now,
        )

    def before(self, intent: StopIntent) -> None:
        self.intent = self.store.request(self._record(intent, self.clock()))

    def after(self, intent: StopIntent, report: StopReport) -> None:
        if self.intent is None or self._record(intent, self.intent.requested_at) != self.intent:
            raise ValueError("Agent stop report has no matching committed intent")
        proof = StopProof(
            term_attempted=report.term_sent, term_delivered=report.term_delivered,
            kill_attempted=report.kill_sent, kill_delivered=report.kill_delivered, error=report.error,
            survivors=tuple(Survivor(pid=each.pid, start=each.start) for each in report.survivors),
        )
        self.store.report(self.intent, proof, self.clock())
