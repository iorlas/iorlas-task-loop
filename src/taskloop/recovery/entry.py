"""Continue a registered recovery owner under the entry's custody and claim lifetime."""

from collections.abc import Callable
from contextlib import nullcontext

from taskloop.attempt_types import AttemptKey, EntryIdentity
from taskloop.drain.models import Identity
from taskloop.recovery.continuation_models import ContinuationResult, State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.models import Intent, Outcome, Result


class RecoveryEntry:
    def __init__(self, continuation: Continuation) -> None:
        self.continuation = continuation

    def registered(self, key: AttemptKey, me: EntryIdentity) -> Intent | Result:
        recovery = self.continuation.recovery
        snapshot = recovery.store.snapshot(key, recovery.clock())
        if isinstance(snapshot, Result):
            return snapshot
        intent = snapshot.intent
        if intent is None or (intent.owner.pid, intent.owner.start, intent.owner.boot) != me or intent.owner.pgid != me[0]:
            return Result(outcome=Outcome.CHANGED, explanation="This entry is not the saved recovery owner.")
        return intent

    def run(
        self, intent: Intent, owner: Identity, clock: Callable[[], float], wait: Callable[[float], None], interval: float,
    ) -> ContinuationResult:
        result = self.continuation(intent.key, owner, intent=intent, custody=nullcontext())
        pending = result.pending
        while result.state is State.PENDING_CAPTURE and pending is not None:
            wait(interval)
            if clock() >= pending.result.admission.deadline:
                break
            result = self.continuation.capture(pending, custody=nullcontext())
        return result
