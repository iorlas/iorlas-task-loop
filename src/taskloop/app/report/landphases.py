"""The land section of the scorecard: from the `land_try` records of the window's runs, how many tries went on, why, and the median
seconds of a try's fetch, rebase and gate."""
import statistics
from collections import Counter
from collections.abc import Sequence
from typing import TypedDict

from taskloop.contracts.log import EngineLog, LandTry


class LandStats(TypedDict):
    tries: int
    retried: int
    causes: dict[str, int]
    median_s: dict[str, float]
    biggest: str


def land_stats(tries: Sequence[LandTry]) -> LandStats:
    """{tries, retried (a try with a `failing`), causes {failing: n}, median_s {phase: s}, biggest (the phase with the largest median)}."""
    causes = Counter(t.failing for t in tries if t.failing)
    median = ({"fetch": statistics.median(t.fetch_s for t in tries), "rebase": statistics.median(t.rebase_s for t in tries),
               "gate": statistics.median(t.gate_s for t in tries)} if tries else {})
    return {"tries": len(tries), "retried": sum(causes.values()), "causes": dict(causes), "median_s": median,
            "biggest": max(median, key=lambda k: median[k]) if median else ""}


def tries_of(rows: Sequence[EngineLog]) -> list[LandTry]:
    return [r for r in rows if isinstance(r, LandTry)]
