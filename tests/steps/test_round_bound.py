"""The in-flight bound of a round (`--max-running`, tl-8bh9.14.76): only work that goes on without the person counts, so a
backlog of ready tasks is started a few at a time, and failed, stuck, unknown, abandoned or hand-started leftovers never
stop the rounds. Over test_round's bench: recording admission, a real in-memory factory.db."""

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import ReadyTracker
from test_round import ENTRY, REQUEST, Admission, Bench, bead, moves, released, seed

from taskloop.admit import AdmitRefused
from taskloop.operations import Failed
from taskloop.round import NextRequest, run_round

DEFAULT = NextRequest("tasks", "/tracker", Path("/checkout"), "auto", "model-m", "high", 30)  # the bound as the CLI leaves it (3)


def backlog(count: int) -> ReadyTracker:
    return ReadyTracker([bead(f"t-{n}", n) for n in range(count)], ready=[f"t-{n}" for n in range(count)])


def test_a_backlog_starts_only_up_to_the_default_bound_not_every_ready_task(factory: sqlite3.Connection) -> None:
    admission = Admission({})
    found = Bench(factory, backlog(5), admission).round(DEFAULT)
    assert moves(found) == [(f"t-{n}", "start", "started") for n in range(3)] and found.stopped == "max_running"
    assert admission.requests == ["t-0", "t-1", "t-2"]  # the others are never claimed


def test_running_tasks_count_towards_the_bound_and_a_full_one_reads_no_tracker(factory: sqlite3.Connection) -> None:
    for number in (1, 2):
        seed(factory, f"tl-{number}", f"attempt-{number}", entry=ENTRY)
    ready = backlog(2)
    bench = Bench(factory, ready)
    bench.seen = "matching"
    found = bench.round(DEFAULT)
    assert ("t-0", "start", "started") in moves(found) and ("t-1", "start", "started") not in moves(found)
    assert found.stopped == "max_running"
    seed(factory, "tl-3", "attempt-3", entry=ENTRY)
    reads = list(ready.ready_reads)
    assert bench.round(DEFAULT).stopped == "max_running" and ready.ready_reads == reads  # three running: no tracker call


def _stuck(bench: Bench) -> None:
    bench.seen, bench.now = "gone", 200  # admitted, its entry gone, past the deadline: `stuck:expired_admitted`


def _unknown(bench: Bench) -> None:
    bench.seen = "unknown"


@pytest.mark.parametrize("arrange", [_stuck, _unknown], ids=["stuck", "unknown"])
def test_stuck_or_unknown_attempts_do_not_count_even_hand_started_ones(
    factory: sqlite3.Connection, arrange: Callable[[Bench], None]
) -> None:
    for number in (1, 2, 3):  # hand-started (no round label): never held, so they would stop the rounds for good
        seed(factory, f"tl-{number}", f"attempt-{number}", entry=ENTRY)
    bench = Bench(factory, backlog(5))
    arrange(bench)
    found = bench.round(DEFAULT)
    assert [each for each in moves(found) if each[1] == "start"] == [(f"t-{n}", "start", "started") for n in range(3)]
    assert found.stopped == "max_running"


def test_an_abandoned_task_is_not_in_flight_and_a_refused_start_does_not_count(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "attempt-1")
    released(factory, "attempt-1", "unclaimed")
    admission = Admission({"t-0": AdmitRefused("claimed_elsewhere")})
    found = Bench(factory, backlog(5), admission).round(DEFAULT)
    assert moves(found) == [("t-0", "start", "refused:claimed_elsewhere"), *[(f"t-{n}", "start", "started") for n in (1, 2, 3)]]
    assert found.stopped == "max_running"


def test_a_max_running_below_one_refuses_the_round(factory: sqlite3.Connection) -> None:
    found = run_round(Bench(factory, ReadyTracker([], ready=[]), Admission({})).ports(), replace(REQUEST, max_running=0))
    assert isinstance(found, Failed) and found.reason == "max_running"
