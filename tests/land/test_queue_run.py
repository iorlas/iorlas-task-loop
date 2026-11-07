"""The queue runner on fakes: at one gate in flight it is serial, at two it gates two PRs at once, it merges in queue order, a conflict or a
red gate ejects its entry and stops the rest from starting, and every entry that left has lost its ref."""
import threading

import pytest

from taskloop.app.land.queue_refs import Conflict, Made
from taskloop.app.land.queue_run import QueueRun
from taskloop.domain.land.queue_model import Entry, Phase

ITEMS = [("a", "ha"), ("b", "hb"), ("c", "hc")]


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
    def __init__(self, in_flight: int, red: set[str] = frozenset(), conflict: frozenset[str] = frozenset()) -> None:
        self.refs, self.red, self.order, self.gated = Refs(conflict), red, [], []
        self.live = self.most = 0
        self.lock = threading.Lock()
        self.together = threading.Barrier(2, timeout=5) if in_flight == 2 else None
        self.run = QueueRun(self.refs, self.gate, self.merge, in_flight=in_flight, main="m0")

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


def test_a_conflict_ejects_the_entry_and_stops_the_building_behind_it():
    w = World(1, conflict=frozenset({"hb"}))
    entries = w.run.run(ITEMS)
    assert [(e.branch, e.phase) for e in entries] == [("a", Phase.MERGED), ("b", Phase.EJECTED), ("c", Phase.WAITING)]
    assert entries[1].reason.startswith("conflict") and w.refs.kept == set()


def test_a_red_gate_ejects_its_entry_and_what_is_green_ahead_of_it_still_merges():
    w = World(1, red=frozenset({"hb"}))
    entries = w.run.run(ITEMS)
    assert [(e.branch, e.phase) for e in entries] == [("a", Phase.MERGED), ("b", Phase.EJECTED), ("c", Phase.WAITING)]
    assert [m[0] for m in w.order] == ["a"] and w.refs.kept == set()


@pytest.mark.parametrize("n", [1, 2])
def test_an_empty_queue_ends(n):
    assert World(n).run.run([]) == []
