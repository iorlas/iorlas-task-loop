"""CRASHMATRIX slice 4: the push went through and the engine died before the land was written down. After the push the land is two
effects, the landed fact and bd's data, each applied once by key. Killed before or between them, a second engine (a new Sync over the
same checkpoint) does the effects that are missing and none that was done: one landed fact, one bd sync, one truth."""
import pytest
from support.narrow_hosts import Stopped
from support.narrow_land import BdOut, FakeSyncHost

from taskloop.app.land.record import Sync

SHA = "abc123def456"


class Killed(Exception):
    pass


class DyingHost(FakeSyncHost):
    """The landed record dies once, as if the process were killed after the push and before the record."""

    dies = True

    def record_land(self, sha: str) -> None:
        if self.dies:
            raise Killed
        super().record_land(sha)


def engines(events: list[str]) -> tuple[DyingHost, BdOut, Sync]:
    host, bd = DyingHost(events), BdOut(events)
    return host, bd, Sync(host, bd)


def second_engine(first: DyingHost, events: list[str]) -> tuple[Sync, BdOut]:
    """A new process: a new host and Sync over the same checkpoint (what the first one wrote), not over the first one's memory."""
    host, bd = FakeSyncHost(events), BdOut(events)
    host.checkpoints = first.checkpoints
    return Sync(host, bd), bd


def test_killed_before_the_landed_fact_the_next_engine_writes_both_once():
    events: list[str] = []
    host, _, first = engines(events)
    with pytest.raises(Killed):
        first.run(SHA)
    assert events == []
    second, _ = second_engine(host, events)
    assert second.run(SHA) == SHA
    assert events == [f"record {SHA}", "sync"]


def test_killed_between_the_landed_fact_and_bd_sync_the_next_engine_only_syncs():
    events: list[str] = []
    host, bd, first = engines(events)
    host.dies, bd.fail = False, True
    with pytest.raises(Stopped):
        first.run(SHA)
    assert events == [f"record {SHA}"]  # the fact is written, the sync is not
    second, next_bd = second_engine(host, events)
    next_bd.fail = False
    second.run(SHA)
    assert events == [f"record {SHA}", "sync"]  # the fact is not written again


def test_a_third_engine_after_both_are_done_changes_nothing():
    events: list[str] = []
    host, _, first = engines(events)
    host.dies = False
    first.run(SHA)
    again, _ = second_engine(host, events)
    again.run(SHA)
    assert events == [f"record {SHA}", "sync"]
