"""The registered-start permit boundary; no launch or process adoption lives here."""

from collections.abc import Callable

from any_agent.procs import Worker

from taskloop.drain.models import Identity
from taskloop.recovery.models import Intent, Outcome
from taskloop.recovery.store import RecoveryStore
from taskloop.session import RegistrationRefused


def registration_hook(store: RecoveryStore, intent: Intent, clock: Callable[[], float]) -> Callable[[Worker], None]:
    def register(worker: Worker) -> None:
        result = store.register(intent, Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot), clock)
        if result.outcome is not Outcome.REGISTERED:
            raise RegistrationRefused(result.explanation)

    return register
