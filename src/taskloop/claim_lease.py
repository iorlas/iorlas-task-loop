"""Keep the tracker claim's lease alive while one step attempt's entry runs (.4.3.1.9): one daemon thread renews it every
BEAT_EVERY_S (a third of bd's fixed 300 s TTL) and stops when the entry's step ends; nothing renews it between steps.

A renewal's outcome is recorded, never acted on: a lost claim stops the renewing, not the step, and nothing here releases
or re-claims. The one word `KeepAlive.word` is what the entry's log line ends with (`claim=<word>`). No IO of its own:
the renewal (`Heartbeat`), the stop event and the clock are injected.
"""

import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Literal, Protocol

type Beat = Literal["held", "lost", "unrenewed"]  # one renewal: renewed; the claim is gone (taken, reverted, closed); unknown
type Heartbeat = Callable[[], Beat]  # bound to one tracker root and task by composition
type HeartbeatFor = Callable[[str, str], Heartbeat]  # (tracker root, task id)
type ClaimWord = Literal["held", "lost", "unrenewed", "fault"]
LEASE_TTL_S = 300.0  # bd 1.3.1's lease, measured; no flag, config key or variable sets it
BEAT_EVERY_S = LEASE_TTL_S / 3
# Each heartbeat is one bd call (composition passes no lock retry) capped at BD_TIMEOUT_S, so a beat takes at most about
# 30 s plus process start, well inside an interval. The bound holds only for that wiring: the renewing thread is a daemon
# and `keeping` waits for it at most BD_TIMEOUT_S + 5 s, so a beat stuck past that may outlive the entry's log line (its
# late result changes nothing that was written; `word` is read under the lock).
BD_TIMEOUT_S = 30.0


class Stop(Protocol):
    """`threading.Event` as the renewing thread uses it: `wait` returns True once `set` was called."""

    def wait(self, timeout: float) -> bool: ...

    def set(self) -> None: ...


class KeepAlive:
    """The renewal state of one claim, shared by the entry's thread and the renewing thread under one lock."""

    def __init__(self, beat: Heartbeat, stop: Stop, clock: Callable[[], float], interval: float = BEAT_EVERY_S) -> None:
        self._beat, self._stop, self._clock, self._interval = beat, stop, clock, interval
        self._lock = threading.Lock()
        self._since = clock()  # the start of the last held beat; before any, this keep-alive's start
        self._held = self._lost = self._faulted = self._lapsed = False

    def renew(self) -> None:
        """One renewal, recorded. Any exception is kept as a fault, never raised (the thread body calls this).

        Judged conservatively: a held beat renewed the lease no earlier than its start, and the lease may have lapsed
        before it if the beat ended a whole TTL after the previous held beat began (so two failed beats in a row, then a
        held one, read as a lapse)."""
        try:
            start = self._clock()
            beat = self._beat()
            end = self._clock()
        except Exception:  # a programming fault ends the renewing; the step goes on
            with self._lock:
                self._faulted = True
            return
        with self._lock:
            if end - self._since >= LEASE_TTL_S:
                self._lapsed = True
            if beat == "held":
                self._since, self._held = start, True
            elif beat == "lost":
                self._lost = True

    def _going(self) -> bool:
        with self._lock:
            return not (self._lost or self._faulted)

    def run(self) -> None:
        """The thread body: renew every interval until stopped, the claim is lost, or a renewal faulted."""
        while self._going() and not self._stop.wait(self._interval):
            self.renew()

    def halt(self) -> None:
        self._stop.set()

    def word(self) -> ClaimWord:
        """`lost` if any renewal said so; else `fault`; else `unrenewed` if no renewal ever held, or the lease may have
        lapsed at some point (judged at each beat and again now, at the end of the step); else `held`."""
        now = self._clock()
        with self._lock:
            if self._lost:
                return "lost"
            if self._faulted:
                return "fault"
            lapsed = self._lapsed or now - self._since >= LEASE_TTL_S
            return "held" if self._held and not lapsed else "unrenewed"


@contextmanager
def keeping(alive: KeepAlive) -> Generator[KeepAlive]:
    """Renew in a daemon thread for the duration of the block; afterwards stop it and wait for it at most one bd call
    longer (daemon, so a bd hung past its own timeout cannot hold the entry's exit)."""
    thread = threading.Thread(target=alive.run, name="claim-lease", daemon=True)
    thread.start()
    try:
        yield alive
    finally:
        alive.halt()
        thread.join(BD_TIMEOUT_S + 5)
