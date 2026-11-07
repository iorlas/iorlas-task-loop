"""Queue metrics use merged timings and the flake policy's inclusive week."""
import pytest

from taskloop.domain.land.queue_flake import WEEK_S
from taskloop.domain.land.queue_metrics import Sample, metrics, percentile
from tlkernel.flakes import FlakeRow


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [([], 0.5, 0.0), ([7.0], 0.9, 7.0), ([40.0, 10.0, 30.0, 20.0], 0.5, 20.0),
     ([40.0, 10.0, 30.0, 20.0], 0.9, 40.0)],
)
def test_percentile(values: list[float], q: float, expected: float) -> None:
    assert percentile(values, q) == expected


def test_metrics() -> None:
    samples = [
        Sample(branch="a", queued_t=10.0, outcome="merged", merged_t=30.0, fetched_t=25.0, gate_s=10.0),
        Sample(branch="b", queued_t=10.0, outcome="merged", merged_t=50.0, fetched_t=35.0, gate_s=20.0),
        Sample(branch="c", queued_t=10.0, outcome="merged", merged_t=70.0, gate_s=30.0),
        Sample(branch="d", queued_t=10.0, outcome="waiting", reason="unused"),
        Sample(branch="e", queued_t=10.0, outcome="gating", gate_s=100.0, wasted_gate_s=10.0),
        Sample(branch="f", queued_t=10.0, outcome="ejected", reason="conflict", wasted_gate_s=20.0),
        Sample(branch="g", queued_t=10.0, outcome="ejected", reason="conflict"),
        Sample(branch="h", queued_t=10.0, outcome="ejected", reason="gate", wasted_gate_s=30.0),
    ]
    result = metrics(samples, [], 100.0)
    assert result.depth == 2
    assert (result.wait_s_p50, result.wait_s_p90) == (40.0, 60.0)
    assert result.ejections == {"conflict": 2, "gate": 1}
    assert result.gate_s_total == 160.0
    assert result.wasted_gate_s_total == 60.0
    assert result.wasted_ratio == 0.5
    assert (result.lag_s_p50, result.lag_s_p90) == (5.0, 15.0)


def test_empty_metrics() -> None:
    result = metrics([], [], 0.0)
    assert result.depth == 0
    assert result.wasted_ratio == 0.0
    assert result.gate_s_total == result.wasted_gate_s_total == 0.0
    assert result.wait_s_p50 == result.wait_s_p90 == 0.0
    assert result.lag_s_p50 == result.lag_s_p90 == 0.0
    assert result.ejections == result.flake_score == {}


def test_flake_score() -> None:
    now = float(WEEK_S + 100)
    flakes = [
        FlakeRow(test="a", t=99.0, how="retry"),
        FlakeRow(test="a", t=100.0, how="retry"),
        FlakeRow(test="a", t=now, how="main"),
        FlakeRow(test="a", t=now + 1.0, how="retry"),
        FlakeRow(test="b", t=now - 1.0, how="retry"),
        FlakeRow(test="old", t=99.0, how="main"),
    ]
    assert metrics([], flakes, now).flake_score == {"a": 2, "b": 1, "old": 0}


@pytest.mark.parametrize(("merged_t", "fetched_t"), [(0.0, 10.0), (10.0, 0.0)])
def test_lag_requires_both_times(merged_t: float, fetched_t: float) -> None:
    sample = Sample(branch="a", queued_t=0.0, outcome="merged", merged_t=merged_t, fetched_t=fetched_t)
    result = metrics([sample], [], 100.0)
    assert result.lag_s_p50 == result.lag_s_p90 == 0.0
