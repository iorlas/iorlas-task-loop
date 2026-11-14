"""Repeated rounds (`rounds.run_rounds`) over a scripted round port, seeded reservation reads and a fake clock whose
`wait` advances time: no real sleep, no signal handler, no process. The graceful stop is the `stopping` port turning True;
the abrupt one a raised `KeyboardInterrupt`."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_reads import SlotUse
from taskloop.exit_codes import exit_code
from taskloop.operations import Ended, Failed, Move, Quiet, Round
from taskloop.round import NextRequest
from taskloop.rounds import CHECK, RoundsPorts, RoundsRequest, abrupt, inputs, run_rounds

HELD = frozenset({("repo", "s1")})
CLEAN = Round("tasks", (Move("tl-1", "report", "running", "a1"),), written=frozenset({("tl-1", "report", "running", "a1")}))
TRACKER = Round("tasks", (), "unavailable:tracker", written=frozenset({("", "stopped", "unavailable:tracker", "")}))


class Bench:
    """The rounds' ports: `results` are the rounds in order (the stop is pressed after the last); `use(t)` is factory.db's
    reservation read at time t; `stop_at`/`raise_at` press a stop or raise `KeyboardInterrupt` at that `wait` call."""

    def __init__(self, results: Sequence[Round | Failed], use: Callable[[float], SlotUse | None] = lambda _t: SlotUse(0, HELD)) -> None:
        self.results, self.use = list(results), use
        self.now, self.cost = 0.0, 0.0
        self.stopped, self.warned = False, 0
        self.stop_at: int | None = None
        self.raise_at: int | None = None
        self.rounds: list[tuple[float, Quiet]] = []
        self.waits: list[float] = []
        self.reads: list[float] = []
        self.lines: list[str] = []
        self.log: Callable[[str], None] = self.lines.append
        self.during: Callable[[], object] = lambda: None

    def round(self, quiet: Quiet) -> Round | Failed:
        self.rounds.append((self.now, quiet))
        self.now += self.cost
        self.during()
        found = self.results.pop(0)
        self.stopped = self.stopped or not self.results
        return found

    def slot_use(self) -> SlotUse | None:
        self.reads.append(self.now)
        return self.use(self.now)

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds
        if len(self.waits) == self.raise_at:
            raise KeyboardInterrupt
        self.stopped = self.stopped or len(self.waits) == self.stop_at

    def warn(self) -> None:
        self.warned += 1

    def run(self, every: int = 60) -> Ended:
        ports = RoundsPorts(self.round, self.slot_use, lambda: 1000 + self.now, lambda: self.now, self.wait, self.log,
                       self.warn, lambda: self.stopped, 7)
        return run_rounds(ports, RoundsRequest("tasks", every))

    def times(self) -> list[float]:
        return [at for at, _quiet in self.rounds]

    def words(self) -> list[str]:
        return [" ".join(line.split(" ")[2:]) for line in self.lines]


def test_rounds_run_at_once_then_every_interval_in_check_slices_and_end_gracefully() -> None:
    bench = Bench([CLEAN, CLEAN, CLEAN])
    bench.cost = 1
    ended = bench.run()
    assert bench.times() == [0, 61, 122] and bench.waits == [CHECK] * 60
    assert ended == Ended("tasks", "interrupted") and exit_code(ended) == 0
    assert bench.words() == ["rounds started every=60 pid=7", "rounds stopped interrupted"]
    assert all(line.startswith("1970-01-01T00:") and line.split(" ")[1] == "tasks" for line in bench.lines)


def test_an_interval_that_is_not_a_multiple_of_the_check_ends_in_a_shorter_slice() -> None:
    bench = Bench([CLEAN, CLEAN])
    bench.run(every=5)
    assert bench.waits == [2, 2, 1] and bench.times() == [0, 5]


def gone(t: float) -> SlotUse:
    return SlotUse(0, HELD if t < 4 else frozenset())


def added(t: float) -> SlotUse:
    return SlotUse(0, HELD if t < 4 else HELD | {("repo", "s2")})


@pytest.mark.parametrize("use, second", [
    (gone, 4),  # a reservation row of the baseline removed: the next round at once
    (added, 60),  # a row added never wakes
    (lambda _t: SlotUse(0, HELD), 60),  # unchanged
    (lambda _t: SlotUse(1, frozenset()), 60),  # an idle baseline has nothing to lose
    (lambda t: SlotUse(0, HELD) if t == 0 else None, 60),  # a failed read neither wakes nor fails
    (lambda _t: None, 60),  # no baseline at all
], ids=["gone", "added", "unchanged", "idle", "unreadable", "no_baseline"])
def test_only_a_removed_reservation_row_wakes_the_next_round(use: Callable[[float], SlotUse | None], second: float) -> None:
    bench = Bench([CLEAN, CLEAN], use)
    bench.run()
    assert bench.times() == [0, second]


def test_a_slot_released_during_the_round_wakes_the_next_round_at_the_first_check() -> None:
    bench = Bench([CLEAN, CLEAN], lambda t: SlotUse(0, HELD if t < 0.5 else frozenset()))  # the round's own verify released it
    bench.cost = 1
    bench.run()
    assert bench.times() == [0, 3]


def test_a_slot_the_round_itself_reserves_wakes_the_next_round_when_its_step_ends() -> None:
    """Live Run H: the round starts with the slot free and admits into it; that step's release must wake the next round."""
    bench = Bench([CLEAN, CLEAN])
    bench.cost = 0.5
    bench.use = lambda t: SlotUse(1, frozenset()) if t == 0 else SlotUse(0, HELD if t < 4 else frozenset())
    bench.run(every=120)
    assert bench.times() == [0, 4.5]


def test_a_failed_baseline_read_is_retried_by_the_next_check() -> None:
    bench = Bench([CLEAN, CLEAN], lambda t: None if t < 2 else SlotUse(0, HELD if t < 6 else frozenset()))
    bench.run()
    assert bench.times() == [0, 6]


def test_a_repeats_takeover_of_a_reserved_slot_does_not_wake() -> None:
    """The baseline is the reserved (repo, slot): a repeat rewrites the row's attempt, the slot stays reserved."""
    bench = Bench([CLEAN, CLEAN], lambda _t: SlotUse(0, HELD))
    bench.run()
    assert bench.times() == [0, 60]


def test_unknown_rounds_back_off_doubling_to_the_cap_and_a_clean_round_returns_to_the_interval() -> None:
    bench = Bench([TRACKER] * 5 + [CLEAN, CLEAN])
    bench.run()
    times = bench.times()
    assert [after - before for before, after in pairwise(times)] == [60, 120, 240, 300, 300, 60]
    assert [each for each in bench.words() if each.startswith("rounds wait")] == [
        "rounds wait seconds=60 after=unavailable:tracker", "rounds wait seconds=120 after=unavailable:tracker",
        "rounds wait seconds=240 after=unavailable:tracker", "rounds wait seconds=300 after=unavailable:tracker",
        "rounds wait seconds=60",
    ]


def test_a_longer_interval_is_its_own_cap() -> None:
    bench = Bench([TRACKER, TRACKER, TRACKER])
    bench.run(every=400)
    assert bench.times() == [0, 400, 800]


@pytest.mark.parametrize("result, backoff", [
    (Failed("unavailable", "store", "locked"), True),  # a whole-round unknown: backs off and goes on
    (Round("tasks", (), "uncertain:launch"), True),
    (Round("tasks", (), "refused:task"), False),  # about one task: written once, tried again next round
    (Round("tasks", (Move("tl-1", "publish", "unavailable:remote", "a1"),)), False),  # a per-task word never backs off
], ids=["store", "launch", "refused_task", "publish"])
def test_what_backs_off_and_what_does_not(result: Round | Failed, backoff: bool) -> None:
    bench = Bench([result, result, CLEAN])
    ended = bench.run()
    assert bench.times() == ([0, 60, 180] if backoff else [0, 60, 120]) and ended.reason == "interrupted"
    assert any(each.startswith("rounds wait") for each in bench.words()) is backoff


def test_each_round_gets_the_previous_rounds_keys_as_quiet_and_the_first_an_empty_set() -> None:
    bench = Bench([CLEAN, TRACKER, CLEAN])
    bench.run()
    assert [quiet for _at, quiet in bench.rounds] == [frozenset(), CLEAN.written, TRACKER.written]


def test_a_whole_round_refusal_ends_the_rounds_with_exit_1() -> None:
    bench = Bench([CLEAN, Failed("refused", "database", "No readable factory.db"), CLEAN])
    ended = bench.run()
    assert ended == Ended("tasks", "refused:database", "No readable factory.db") and exit_code(ended) == 1
    assert bench.words()[-1] == "rounds stopped refused:database" and len(bench.rounds) == 2 and len(bench.waits) == 30


def test_a_graceful_stop_while_waiting_ends_after_the_current_slice() -> None:
    bench = Bench([CLEAN, CLEAN])
    bench.stop_at = 3
    ended = bench.run()
    assert ended == Ended("tasks", "interrupted") and bench.times() == [0] and len(bench.waits) == 3
    assert bench.words()[-1] == "rounds stopped interrupted"


def test_a_graceful_stop_during_a_round_ends_without_a_wait_or_another_round() -> None:
    bench = Bench([Round("tasks", (), "interrupted"), CLEAN])

    def pressed() -> None:
        bench.stopped = True

    bench.during = pressed
    ended = bench.run()
    assert ended.reason == "interrupted" and bench.times() == [0] and bench.waits == []


@pytest.mark.parametrize("where", ["wait", "round"])
def test_an_abrupt_stop_writes_its_line_and_passes_through(where: str) -> None:
    bench = Bench([CLEAN, CLEAN, CLEAN])
    if where == "wait":
        bench.raise_at = 5
    else:
        def interrupted() -> None:
            if len(bench.rounds) == 2:
                raise KeyboardInterrupt

        bench.during = interrupted
    with pytest.raises(KeyboardInterrupt):
        bench.run()
    assert bench.words()[:1] == ["rounds started every=60 pid=7"]
    assert bench.words()[-1] == "rounds stopped abrupt"
    assert sum("stopped" in line for line in bench.lines) == 1


def test_an_abrupt_stop_before_the_rounds_started_writes_no_line() -> None:
    bench = Bench([CLEAN])

    def pressed(_line: str) -> None:
        raise KeyboardInterrupt

    bench.log = pressed
    with pytest.raises(KeyboardInterrupt):
        bench.run()
    assert bench.rounds == []


def test_an_unwritable_log_changes_nothing_but_warns_once_each_time_it_stops_being_written() -> None:
    def broken(_line: str) -> None:
        raise PermissionError("rounds.log")

    unlogged = [replace(each, logged=False) for each in (CLEAN, TRACKER, CLEAN)]  # its rounds' own lines fail too
    failing, written = Bench(unlogged), Bench([CLEAN, TRACKER, CLEAN])
    failing.log = broken
    assert failing.run() == written.run() and failing.times() == written.times()
    assert failing.warned == 1 and written.warned == 0
    flapping = Bench([Round("tasks", (), logged=False), CLEAN, Round("tasks", (), logged=False)])
    flapping.run()
    assert flapping.warned == 2


REQUEST = NextRequest("tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), Overrides(model="m", effort="high"), 30)


@pytest.mark.parametrize("change, reason", [
    ({"backlog": "a/b"}, "backlog"), ({"backlog": ""}, "backlog"), ({"backlog": "a b"}, "backlog"), ({"label": " "}, "label"),
    ({"minutes": 0}, "choices"), ({"minutes": 7 * 24 * 60 + 1}, "choices"),
])
def test_the_rounds_choices_are_checked_before_anything(change: dict[str, str | int], reason: str) -> None:
    fields = {"backlog": "tasks", "label": "auto", "model": "m", "effort": "high", "minutes": 30} | change
    request = NextRequest(
        str(fields["backlog"]),
        "/tracker",
        Path("/checkout"),
        str(fields["label"]),
        StepSettings(),
        Overrides(model=str(fields["model"]), effort=str(fields["effort"])),
        int(fields["minutes"]),
    )
    refused = inputs(request)
    assert refused is not None and (refused.kind, refused.reason) == ("refused", reason)
    assert inputs(REQUEST) is None
    assert inputs(replace(REQUEST, overrides=Overrides(effort="ultra"))) is None  # which efforts exist is the vendor's to say


def test_the_abrupt_line_is_best_effort() -> None:
    lines: list[str] = []
    abrupt(lines.append, lambda: 0, "tasks")
    assert lines == ["1970-01-01T00:00:00Z tasks rounds stopped abrupt"]

    def failing(_line: str) -> None:
        raise OSError("full")

    def pressed(_line: str) -> None:
        raise KeyboardInterrupt

    abrupt(failing, lambda: 0, "tasks")
    abrupt(pressed, lambda: 0, "tasks")
