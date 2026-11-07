"""Retry-passes defines a flake in this simulation; the design accepts the p^3 cost of three independent failures."""
import random

import pytest

from taskloop.domain.land.queue_flake import Attempt, FlakeRow, Verdict, decide, row, score

RED = Attempt(rc=1, out="assertion failed")
GREEN = Attempt(rc=0, out="passed")
OTHER = Attempt(rc=1, out="another assertion failed")


@pytest.mark.parametrize(
    ("red", "retry", "main", "retried", "expected"),
    [
        (RED, None, None, False, Verdict.RETRY),
        (RED, GREEN, None, True, Verdict.FLAKE),
        (RED, GREEN, None, False, Verdict.FLAKE),
        (RED, RED, None, True, Verdict.MAIN),
        (RED, OTHER, None, True, Verdict.MAIN),
        (RED, RED, None, False, Verdict.MAIN),
        (RED, OTHER, None, False, Verdict.MAIN),
        (Attempt(rc=124, out="timeout"), None, None, False, Verdict.MAIN),
        (Attempt(rc=1, out="Weapon.cs(52,17): error CS1002"), None, None, False, Verdict.MAIN),
        (RED, RED, RED, True, Verdict.MAIN_RED),
        (RED, RED, GREEN, True, Verdict.BLAME),
        (RED, None, None, True, Verdict.MAIN),
        (RED, None, RED, True, Verdict.MAIN_RED),
        (RED, None, GREEN, True, Verdict.BLAME),
    ],
)
def test_decide(red: Attempt, retry: Attempt | None, main: Attempt | None, retried: bool, expected: Verdict) -> None:
    assert decide(red, retry, main, retried=retried) is expected


@pytest.mark.parametrize(
    ("verdict", "how"),
    [(Verdict.RETRY, None), (Verdict.MAIN, None), (Verdict.BLAME, None),
     (Verdict.FLAKE, "retry"), (Verdict.MAIN_RED, "main")],
)
def test_row(verdict: Verdict, how: str | None) -> None:
    result = row("flaky", 42.0, verdict, GREEN if verdict is Verdict.FLAKE else RED)
    if how is None:
        assert result is None
    else:
        assert result == FlakeRow(test="flaky", t=42.0, how=how, run="")


def test_score() -> None:
    rows = [FlakeRow(test="flaky", t=t, how="retry") for t in (89.0, 90.0, 95.0, 100.0, 101.0)]
    rows.append(FlakeRow(test="other", t=95.0, how="main"))
    assert score(rows, "flaky", now=100.0, week_s=10.0) == 3
    assert score(rows, "missing", now=100.0, week_s=10.0) == 0
    assert score([], "flaky", now=100.0) == 0
    assert score([FlakeRow(test="flaky", t=0.0, how="main")], "flaky", now=7 * 86400) == 1


class Runner:
    """Script one PR: a possible first red followed by a passing retry and main."""

    def __init__(self, first_red: bool) -> None:
        self.first_red = first_red
        self.calls = 0

    def run(self) -> Attempt:
        self.calls += 1
        return RED if self.first_red and self.calls == 1 else GREEN


@pytest.mark.parametrize("p", [0.1, 0.3])
def test_flake_simulation(p: float) -> None:
    rng = random.Random(732)
    failures = flakes = blamed = baseline_ejections = 0
    for _ in range(300):
        runner = Runner(rng.random() < p)
        red = runner.run()
        if red.rc == 0:
            continue
        failures += 1
        baseline_ejections += 1  # Policy off: blame the first red.
        retry = main = None
        retried = False
        while True:
            verdict = decide(red, retry, main, retried=retried)
            if verdict is Verdict.RETRY:
                assert not retried
                retry = runner.run()
                retried = True
            elif verdict is Verdict.MAIN:
                assert main is None
                main = runner.run()
            else:
                flakes += verdict is Verdict.FLAKE
                blamed += verdict is Verdict.BLAME
                break
        assert runner.calls == 2
    assert blamed == 0
    assert flakes == failures
    assert baseline_ejections > 0
    assert baseline_ejections == failures
