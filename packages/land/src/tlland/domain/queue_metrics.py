"""Pure queue counts and timings for the metrics in merge-queue.md sections 9 and 14."""
from collections import Counter
from collections.abc import Sequence
from math import ceil
from typing import Final, final

from tlkernel.flakes import FlakeRow
from tlkernel.wire import Rec

from tlland.domain.queue_flake import score

P50: Final = 0.5
P90: Final = 0.9


@final
class Sample(Rec):
    branch: str
    queued_t: float
    outcome: str
    gate_s: float = 0.0
    wasted_gate_s: float = 0.0
    reason: str = ""
    merged_t: float = 0.0
    fetched_t: float = 0.0


@final
class Metrics(Rec):
    depth: int
    wait_s_p50: float
    wait_s_p90: float
    gate_s_total: float
    wasted_gate_s_total: float
    wasted_ratio: float
    ejections: dict[str, int]
    flake_score: dict[str, int]
    lag_s_p50: float
    lag_s_p90: float


def percentile(values: Sequence[float], q: float) -> float:
    """Return the nearest-rank quantile, or zero when no values exist."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(q * len(ordered)) - 1))]


def metrics(samples: Sequence[Sample], flakes: Sequence[FlakeRow], now: float) -> Metrics:
    """Aggregate queue samples; only merged PRs contribute useful gate time and waits."""
    merged = [s for s in samples if s.outcome == "merged"]
    waits = [s.merged_t - s.queued_t for s in merged]
    lags = [s.merged_t - s.fetched_t for s in merged if s.merged_t and s.fetched_t]
    useful = sum(s.gate_s for s in merged)
    wasted = sum(s.wasted_gate_s for s in samples)
    return Metrics(
        depth=sum(s.outcome in ("waiting", "built", "gating", "green", "red") for s in samples),
        wait_s_p50=percentile(waits, P50),
        wait_s_p90=percentile(waits, P90),
        gate_s_total=sum(s.gate_s for s in samples),
        wasted_gate_s_total=wasted,
        wasted_ratio=wasted / (wasted + useful) if wasted + useful else 0.0,
        ejections=dict(Counter(s.reason for s in samples if s.outcome == "ejected")),
        flake_score={test: score(flakes, test, now) for test in sorted({r.test for r in flakes})},
        lag_s_p50=percentile(lags, P50),
        lag_s_p90=percentile(lags, P90),
    )
