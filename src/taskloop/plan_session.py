"""Live registration gate and native-session latch for one execution; both are bounded and hold no retry."""

import threading
from collections.abc import Callable
from typing import Literal

from any_agent.procs import Worker

from taskloop.plan_store import PlanStore, StoreRefused, StoreUnavailable
from taskloop.plan_types import Admission, ExecutionFacts, SessionInput


class GateRefused(Exception):
    """Registration was refused, so the gated target must not be executed."""


def registration_gate(store: PlanStore, admission: Admission, clock: Callable[[], float]) -> Callable[[Worker], None]:
    """The started hook: deadline and boot-aware identity are checked behind the gate; any refusal raises."""

    def register(worker: Worker) -> None:
        if clock() >= admission.deadline:
            raise GateRefused("expired")
        if store.register(admission, worker) == "conflict":
            raise GateRefused("registration_conflict")

    return register


class SessionLatch:
    """Receives refs on the output pump: one conditional publication per callback, never raising into the pump.

    Keeps the first ref seen while unaccepted, and a flag when a different ref arrives; never overwrites.
    """

    def __init__(self, store: PlanStore, admission: Admission) -> None:
        self._store, self._admission = store, admission
        self._lock = threading.Lock()
        self._seen: str | None = None
        self._accepted = False
        self._conflict = False
        self._fault: str | None = None

    def observe(self, ref: str) -> None:
        with self._lock:
            try:
                if self._seen is None:
                    self._seen = ref
                elif ref != self._seen:
                    self._conflict = True
                if ref == self._seen or self._accepted:
                    self._publish(ref)
            except StoreUnavailable:
                pass
            except StoreRefused as error:
                self._fault = f"refused:{error}"
            except Exception as error:  # a programming fault is retained with its type, never raised into the output pump
                self._fault = f"unexpected:{type(error).__name__}"

    def _publish(self, ref: str) -> None:
        status = self._store.session(self._admission, ref)
        if status == "conflict":
            self._conflict = True
        elif ref == self._seen:
            self._accepted = True

    def snapshot(self) -> SessionInput:
        with self._lock:
            return SessionInput(None if self._accepted else self._seen, self._conflict, self._fault)


def reconcile(
    store: PlanStore, admission: Admission, sessions: SessionInput, facts: ExecutionFacts
) -> Literal["complete", "pending", "conflict", "fault"]:
    """Publish the unaccepted first ref and the reported terminal ref, one conditional write each."""
    conflict, fault, pending = sessions.conflict, sessions.fault is not None, False
    for ref in dict.fromkeys(r for r in (sessions.first_ref, facts.session) if r is not None):
        try:
            conflict = store.session(admission, ref) == "conflict" or conflict
        except StoreUnavailable:
            pending = True
        except StoreRefused:
            fault = True
    return "conflict" if conflict else "fault" if fault else "pending" if pending else "complete"
