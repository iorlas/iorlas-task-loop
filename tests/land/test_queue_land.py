"""`QueueLand` on fakes: open PRs go through the queue (gated on Q(N), merged in order, refs dropped), a red gate ejects its entry and
stops the run naming it, and anything the queue cannot judge takes the serial path. `Stack(queue=False)` never comes here."""
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import pytest

from taskloop.app.land import queue_land
from taskloop.app.land.cmds import Stop
from taskloop.app.land.queue_land import Queued, QueueLand
from taskloop.app.land.queue_refs import Made
from taskloop.app.land.stack import HeadMoved, Stack
from tlkernel.forge import CLOSED, OPEN, StackItem
from tlkernel.queue_doc import QueueDoc


class FakeRefs:
    kept: ClassVar[set[str]] = set()

    def __init__(self, cmds, repo) -> None:
        self.n = 0

    def make(self, n, parent, head):
        ref = f"refs/tl/queue/{n}-{head}"
        FakeRefs.kept.add(ref)
        return Made(q=f"q{n}", tree=f"t{n}", ref=ref)

    def drop(self, ref) -> None:
        FakeRefs.kept.discard(ref)


class FakeDoc:
    def __init__(self):
        self.value = None
        self.writes = []

    def get(self):
        return self.value

    def write(self, value):
        self.value = value
        self.writes.append(value)


class World:
    def __init__(self, *, states=(OPEN, OPEN, OPEN), red=frozenset(), profile_change=None) -> None:
        FakeRefs.kept = set()
        self.names = ["a", "b", "c"]
        self.serial, self.delivered, self.judged = [], [], []
        pr = {n: SimpleNamespace(state=s) for n, s in zip(self.names, states, strict=False)}
        self.stack = SimpleNamespace(
            queue_doc=FakeDoc(),
            profile_change=profile_change, jobs=1, repo="/r", cmds=None, last="", trees=SimpleNamespace(main_ref="origin/main"),
            resolve=lambda item: (item.branch, "h" + item.branch, pr[item.branch]), item=lambda item: self.serial.append(item.branch),
            forge=SimpleNamespace(fetch=lambda: None),
            beads=SimpleNamespace(show=lambda bead: None),
            git=SimpleNamespace(merge_base=lambda repo, main, oid: main, diff_entries=lambda repo, base, oid: [],
                                rev_parse=lambda d, rev: "main0" if rev == "origin/main" else rev),
            gate=SimpleNamespace(judge_queue=lambda q, parent, lock: self.judged.append((q, parent)) or q not in red),
            deliver=self.deliver)

    def deliver(self, item, queued: Queued) -> None:
        self.delivered.append((item.branch, queued.q, queued.tree))
        self.stack.last = f"merge-{item.branch}"

    def run(self, n: int = 3) -> None:
        with mock.patch.object(queue_land, "QueueRefs", FakeRefs):
            QueueLand(self.stack).run([StackItem(branch=b) for b in self.names[:n]])


def test_open_prs_are_gated_on_their_queue_commit_and_merged_in_order_with_their_refs_dropped():
    w = World()
    w.run()
    assert w.delivered == [("a", "q1", "t1"), ("b", "q2", "t2"), ("c", "q3", "t3")]
    assert w.serial == [] and FakeRefs.kept == set()
    assert w.judged == [("q1", "q1^"), ("q2", "q2^"), ("q3", "q3^")]


def test_a_red_gate_ejects_its_entry_merges_those_ahead_and_names_it():
    w = World(red={"q2"})
    with pytest.raises(Stop) as stop:
        w.run()
    assert [d[0] for d in w.delivered] == ["a", "c"]
    assert "queue: b ejected" in stop.value.why and "2 merged" in stop.value.why
    assert FakeRefs.kept == set()


@pytest.mark.parametrize("world", [{"states": (OPEN, CLOSED, OPEN)}, {"profile_change": "owner says so"}],
                         ids=["not open", "profile change"])
def test_what_the_queue_cannot_judge_takes_the_serial_path(world):
    w = World(**world)
    w.run()
    assert w.serial == ["a", "b", "c"] and w.delivered == []


def test_one_item_takes_the_serial_path():
    w = World()
    w.run(1)
    assert w.serial == ["a"] and w.delivered == []


def test_a_head_that_moved_while_queued_is_never_merged():
    stack = mock.create_autospec(Stack, instance=True)
    with pytest.raises(HeadMoved):
        Stack.crossing(stack, "task/a", "new" * 13, Queued(head="old" * 13, q="q1", tree="t1"))


@pytest.mark.parametrize("branch,bead", [("a", "child"), ("task/child", "")])
def test_refusing_enqueue_builds_no_refs_and_merges_nothing(branch, bead):
    world = World()
    parent = SimpleNamespace(id="parent", type="blocks", status="open")
    world.stack.beads.show = lambda name: SimpleNamespace(dependencies=[parent]) if name == "child" else None
    world.stack.resolve = lambda item: (item.branch, "head", None)
    with mock.patch.object(queue_land, "QueueRefs", FakeRefs), pytest.raises(Stop) as stop:
        QueueLand(world.stack).run([StackItem(branch=branch, bead=bead), StackItem(branch="b")])
    assert stop.value.why == "queue: child waits for parent (not merged to main)"
    assert FakeRefs.kept == set()
    assert world.delivered == []
    assert world.judged == []


def test_run_persists_initial_entries_and_every_change():
    world = World()
    world.run()
    doc = world.stack.queue_doc
    assert [e.phase for e in doc.writes[0].entries] == ["waiting"] * 3
    assert [e.branch for e in doc.value.entries] == world.names
    assert all(e.phase == "merged" for e in doc.value.entries)
    assert len(doc.writes) > 3


def test_stale_document_is_recovered_once_before_new_run():
    world = World()
    stale = QueueDoc(entries=[], in_flight=1, last_base="old")
    world.stack.queue_doc.value = stale
    with mock.patch.object(queue_land, "recover") as recovery:
        world.run()
    recovery.assert_called_once_with(world.stack, stale, mock.ANY)


@pytest.mark.parametrize("stored,expected", [(None, 1), (-3, 1), (2, 2), (9, 4)])
def test_stored_in_flight_is_restored_and_clamped(stored, expected):
    world = World()
    world.stack.jobs = 4
    if stored is not None:
        world.stack.queue_doc.value = QueueDoc(entries=[], in_flight=stored, last_base="old")
    with mock.patch.object(queue_land, "recover"), mock.patch.object(queue_land, "enqueue", return_value=4):
        world.run()
    writes = world.stack.queue_doc.writes
    assert writes[0].in_flight == expected
    assert writes[-1].in_flight == min(4, expected + 3)


def test_overlap_enqueue_result_caps_the_controller_at_one():
    world = World()
    world.stack.jobs = 4
    world.stack.queue_doc.value = QueueDoc(entries=[], in_flight=4, last_base="old")
    with mock.patch.object(queue_land, "recover"), mock.patch.object(queue_land, "enqueue", return_value=1):
        world.run()
    assert all(doc.in_flight == 1 for doc in world.stack.queue_doc.writes)
