"""The queue runner on fakes: at one gate in flight it is serial, at two it gates two PRs at once, it merges in queue order, a conflict or a
red gate ejects its entry and the rest continue, and every entry that left has lost its ref."""
import threading
from concurrent.futures import Future

import pytest

from taskloop.app.land import queue_run
from taskloop.app.land.queue import InFlight
from taskloop.app.land.queue_refs import Conflict, Made
from taskloop.app.land.queue_run import QueueRun
from taskloop.domain.land.queue_in_flight import Cause
from taskloop.domain.land.queue_in_flight import Event as FlightEvent
from taskloop.domain.land.queue_model import Entry, Phase, Reset

ITEMS = [("a", "ha"), ("b", "hb"), ("c", "hc")]


def flight(n: int) -> InFlight:
    controller = InFlight(cap=n)
    controller.current = n
    return controller


class Refs:
    def __init__(self, conflict: frozenset[str] = frozenset()) -> None:
        self.conflict = conflict
        self.kept: set[str] = set()
        self.made: list[tuple[int, str, str]] = []

    def make(self, n: int, parent: str, head: str):
        self.made.append((n, parent, head))
        if head in self.conflict:
            return Conflict(why="CONFLICT (content): f")
        ref = f"refs/tl/queue/{n}-{head}"
        self.kept.add(ref)
        return Made(q=f"q{n}", tree=f"t{n}", ref=ref)

    def drop(self, ref: str) -> None:
        self.kept.discard(ref)


class World:
    def __init__(self, in_flight: int, red: frozenset[str] = frozenset(), conflict: frozenset[str] = frozenset()) -> None:
        self.refs, self.red, self.order, self.gated = Refs(conflict), red, [], []
        self.live = self.most = 0
        self.lock = threading.Lock()
        self.together = threading.Barrier(2, timeout=5) if in_flight == 2 else None
        self.run = QueueRun(self.refs, self.gate, self.merge, flight=flight(in_flight), main="m0")

    def gate(self, entry: Entry) -> bool:
        with self.lock:
            self.live += 1
            self.most = max(self.most, self.live)
            self.gated.append(entry.branch)
        try:
            if self.together is not None and len(self.gated) <= 2:
                self.together.wait()  # both gates must be in flight for this to pass
            return entry.head not in self.red
        finally:
            with self.lock:
                self.live -= 1

    def merge(self, entry: Entry, main: str) -> str:
        self.order.append((entry.branch, entry.q, main))
        return f"m{len(self.order)}"


def test_at_one_in_flight_the_queue_is_serial_and_lands_in_order():
    w = World(1)
    w.run.run(ITEMS)
    assert w.run.merged() == ["a", "b", "c"] and w.most == 1
    assert [m[0] for m in w.order] == ["a", "b", "c"]


def test_at_two_in_flight_two_prs_are_gated_at_once_and_merged_in_order():
    w = World(2)
    w.run.run(ITEMS[:2])
    assert w.most == 2 and [m[0] for m in w.order] == ["a", "b"]  # the barrier only passes with both gates running


def test_q_chains_on_the_queue_ahead_until_the_head_lands_then_on_the_new_main():
    w = World(1)
    w.run.run(ITEMS)
    assert w.refs.made == [(1, "m0", "ha"), (2, "m1", "hb"), (3, "m2", "hc")]  # main moved by each landing


def test_queue_refs_are_gone_when_everything_has_left():
    w = World(2)
    w.run.run(ITEMS[:2])
    assert w.refs.kept == set()


def test_a_conflict_ejects_the_entry_and_continues_building_behind_it():
    w = World(1, conflict=frozenset({"hb"}))
    entries = w.run.run(ITEMS)
    assert [(e.branch, e.phase) for e in entries] == [("a", Phase.MERGED), ("b", Phase.EJECTED), ("c", Phase.MERGED)]
    assert entries[1].reason.startswith("conflict") and w.refs.kept == set()


def test_a_red_gate_ejects_its_entry_and_what_is_green_ahead_of_it_still_merges():
    w = World(1, red=frozenset({"hb"}))
    entries = w.run.run(ITEMS)
    assert [(e.branch, e.phase) for e in entries] == [("a", Phase.MERGED), ("b", Phase.EJECTED), ("c", Phase.MERGED)]
    assert [m[0] for m in w.order] == ["a", "c"] and w.refs.kept == set()


@pytest.mark.parametrize("n", [1, 2])
def test_an_empty_queue_ends(n):
    assert World(n).run.run([]) == []


@pytest.mark.parametrize("red,conflict", [(frozenset(), frozenset()), (frozenset({"ha"}), frozenset()),
                                          (frozenset(), frozenset({"ha"}))])
def test_on_change_observes_initial_entries_and_every_transition(red, conflict):
    world = World(1, red=red, conflict=conflict)
    snapshots = []
    world.run.on_change = lambda entries: snapshots.append(list(entries))
    entries = world.run.run(ITEMS[:1])
    expected = [Phase.WAITING]
    if conflict:
        expected += [Phase.EJECTED]
    else:
        expected += [Phase.BUILT, Phase.GATING, Phase.RED if red else Phase.GREEN]
        if red:
            expected += [Phase.EJECTED]
        if not red:
            expected += [Phase.MERGED]
    expected += [expected[-1]]  # Ref removal is also an observed event.
    if conflict:
        expected.pop()  # A conflict never acquired a ref.
    assert [rows[0].phase for rows in snapshots] == expected
    assert snapshots[-1] == entries


@pytest.mark.parametrize("cap,expected", [(2, [1, 2, 2, 2]), (4, [1, 2, 3, 4])])
def test_merges_grow_the_controller_to_its_cap(cap, expected):
    controller = InFlight(cap=cap)
    currents = []

    def changed(entries):
        if not currents or len(controller.accounts) == len(currents):
            currents.append(controller.current)

    runner = QueueRun(Refs(), lambda entry: True, lambda entry, main: entry.q,
                      flight=controller, main="m0", clock=lambda: 0.0, on_change=changed)
    runner.run(ITEMS)
    assert runner.merged() == ["a", "b", "c"]
    assert currents == expected
    assert [account.pr for account in controller.accounts] == [1, 2, 3]


@pytest.mark.parametrize("red,conflict", [(True, False), (False, True)])
def test_red_gate_and_conflict_eject_halve_the_controller(red, conflict):
    controller = flight(4)
    refs = Refs(frozenset({"ha"}) if conflict else frozenset())
    runner = QueueRun(refs, lambda entry: not red, lambda entry, main: entry.q,
                      flight=controller, main="m0", clock=lambda: 0.0)
    entries = runner.run(ITEMS[:1])
    assert entries[0].phase is Phase.EJECTED
    assert controller.current == 2
    assert not controller.accounts


def test_merged_account_records_gate_seconds_at_settle():
    ticks = iter([10.0, 17.5])
    controller = InFlight(cap=4)
    runner = QueueRun(Refs(), lambda entry: True, lambda entry, main: entry.q,
                      flight=controller, main="m0", clock=lambda: next(ticks))
    runner.run(ITEMS[:1])
    assert controller.accounts[0].useful_gate_s == 7.5


class ScheduledPool:
    """A fake executor whose running tasks finish only when the runner waits."""

    def __init__(self, **_kwargs):
        self.entries = {}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def submit(self, gate, entry):
        future = Future()
        future.set_running_or_notify_cancel()
        self.entries[future] = (gate, entry)
        return future


@pytest.mark.parametrize("order,own_red,expected", [
    (["a", "b", "b", "c"], "a", ["b", "c"]),
    (["b", "a", "b", "c"], "a", ["b", "c"]),
    (["b", "a", "c"], "b", ["a", "c"]),
])
def test_attribution_rebuilds_dependents_and_discards_invalidated_gates(monkeypatch, order, own_red, expected):
    pool = ScheduledPool()
    monkeypatch.setattr(queue_run, "ThreadPoolExecutor", lambda **kwargs: pool)
    schedule = iter(order)
    ticks = [0.0]

    def clock():
        return ticks[0]

    def finish(running, **_kwargs):
        branch = next(schedule)
        future = next(f for f in running if pool.entries[f][1].branch == branch)
        gate, entry = pool.entries[future]
        ticks[0] += 5.0
        if future in runner.doomed:
            future.set_exception(RuntimeError("invalidated result"))
        else:
            future.set_result(gate(entry))
        return {future}, set(running) - {future}

    monkeypatch.setattr(queue_run, "wait", finish)
    controller = flight(2)
    events = []
    happened = controller.happened

    def record(event):
        events.append(event)
        return happened(event)

    monkeypatch.setattr(controller, "happened", record)
    snapshots = []
    refs = Refs()
    runner = QueueRun(refs, lambda e: e.branch != own_red and not (own_red == "a" and e.after == "a"),
                      lambda e, main: e.q, flight=controller, main="main", clock=clock,
                      on_change=lambda es: snapshots.append(list(es)))
    entries = runner.run(ITEMS)
    assert runner.merged() == expected
    assert [e.branch for e in entries if e.phase is Phase.EJECTED] == [own_red]
    assert events.count(FlightEvent.GATE_FAILED) == 1
    assert refs.kept == set()
    assert not runner.started and not runner.doomed
    if own_red == "a":
        assert any(a.wasted_gate_s >= 5.0 and Cause.CULPRIT_AHEAD in a.causes for a in controller.accounts)
        assert not any(e.branch == "b" and e.phase is Phase.EJECTED for es in snapshots for e in es)
    else:
        assert any(es[0].phase is Phase.GATING and es[1].phase is Phase.RED for es in snapshots)


def test_reset_cancels_a_gate_that_has_not_started(monkeypatch):
    future = Future()
    controller = flight(2)
    refs = Refs()
    refs.kept.add("stale-ref")
    runner = QueueRun(refs, lambda e: True, lambda e, main: e.q,
                      flight=controller, main="main", clock=lambda: 9.0)
    runner.entries = [Entry(branch="b", head="hb", phase=Phase.GATING, q="q", ref="stale-ref", after="a")]
    runner.started["b"] = 2.0
    running = {future: "b"}
    runner.reset(Reset("b", "stale-ref"), running)
    assert future.cancelled()
    assert controller.pending_s == 7.0
    assert controller.pending_causes == [Cause.CULPRIT_AHEAD]
    monkeypatch.setattr(queue_run, "wait", lambda *args, **kwargs: ({future}, set()))
    runner.settle(running)
    assert runner.entries == [Entry(branch="b", head="hb")]
    assert not running and not runner.doomed and not runner.started and not refs.kept
