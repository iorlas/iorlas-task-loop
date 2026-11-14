"""Compose read-only recovery observations and project their conservative status gate."""

from collections.abc import Callable
from contextlib import nullcontext
from typing import Literal

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Seen
from taskloop.hold_store import HoldStore
from taskloop.ids import NativeIds
from taskloop.recovery.models import Claim, ClaimState, Observations, Result
from taskloop.recovery.observe import NativeProcesses
from taskloop.recovery.recover import Recovery
from taskloop.recovery.store import RecoveryStore


def reader(store: AttemptStore, clock: Callable[[], float]) -> Callable[[AttemptKey], Observations | Result]:
    return Recovery(RecoveryStore(store.connect), NativeProcesses(),
                    lambda _admission: Claim(state=ClaimState.UNKNOWN, explanation="Status has no claim authority."),
                    lambda _admission: nullcontext(), clock, NativeIds()).status


def process_gate(
    store: AttemptStore, key: AttemptKey, read: Callable[[AttemptKey], Observations | Result], expired: bool,
) -> Literal["unknown", "wait", "stuck:hung"] | None:
    try:
        if HoldStore(store.connect, store.begin).of_attempts((key.attempt_id,)):
            return None
        observed = read(key)
    except StoreUnavailable:
        return "unknown"
    if isinstance(observed, Result):
        return "unknown"
    states = (observed.entry.seen, observed.worker.seen, *(() if observed.owner is None else (observed.owner.seen,)))
    if Seen.UNKNOWN in states:
        return "unknown"
    if Seen.ALIVE in states:
        return "stuck:hung" if expired else "wait"
    return None
