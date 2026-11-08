"""The long silences of a worker's stream, kept as history rows to learn the real distribution of gaps."""

import time
from collections.abc import Callable

from any_agent.watch import LONG_GAP_S, Watchdog

from delegate.contracts.history import GapRow


def flush(
    dog: Watchdog, add: Callable[[GapRow], object], lane: str, model: str, finished: bool, now: Callable[[], float] = time.time
) -> None:
    """One history row per inter-event gap over LONG_GAP_S (a stream that died inside one counts too). `add` is the history writer; this
    never raises."""
    try:
        tail = dog.clock() - dog.last
        for g in dog.gaps + ([round(tail, 1)] if dog.events and tail > LONG_GAP_S else []):
            add(GapRow(ts=now(), lane=lane, model=model, gap_s=g, finished=finished))
    except Exception:
        pass
