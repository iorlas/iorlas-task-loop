"""INTAKE (tl-7i9k.19): agent-filed follow-ups wait as `deferred` with the label `from-review`; at most K a day are promoted to open."""

import pytest

from tlkernel import beadsport, memory_beads
from tlkernel import deferrals as intake


def filed(store, n, priority=None):
    ids = []
    for i in range(n):
        made = store.create(beadsport.NewBead(title=f"f{i}", description="d", labels=[intake.FROM_REVIEW], priority=priority))
        intake.defer(store, made)
        ids.append(made)
    return ids


def status_of(store, ids):
    return [b.status for b in (store.show(i) for i in ids) if b is not None]


def test_defer_leaves_the_bead_labelled_and_out_of_ready():
    store = memory_beads.MemoryBeads()
    (made,) = filed(store, 1)
    got = store.show(made)
    assert got is not None and got.status == "deferred" and intake.FROM_REVIEW in got.labels
    assert store.ready() == []


def test_k_a_day_are_promoted_and_the_rest_wait():
    store = memory_beads.MemoryBeads()
    ids = filed(store, 5)
    assert intake.promote(store, 3, "2026-11-06") == ids[:3]
    assert status_of(store, ids) == ["open"] * 3 + ["deferred"] * 2
    assert intake.promote(store, 3, "2026-11-06") == []  # the day's budget is spent
    assert intake.promote(store, 3, "2026-11-07") == ids[3:]  # the next day takes the rest


def test_a_promoted_bead_that_closed_the_same_day_still_counts():
    store = memory_beads.MemoryBeads()
    ids = filed(store, 4)
    for made in intake.promote(store, 2, "2026-11-06"):
        store.close(made, "done")
    assert intake.promote(store, 2, "2026-11-06") == []
    assert len(store.find(beadsport.BeadQuery(label=intake.PROMOTED + "2026-11-06", include_closed=True))) == 2
    assert status_of(store, ids[2:]) == ["deferred", "deferred"]


def test_higher_priority_goes_first_and_off_promotes_nothing():
    store = memory_beads.MemoryBeads()
    low = filed(store, 1, priority=3)
    high = filed(store, 1, priority=1)
    assert intake.promote(store, 0, "2026-11-06") == []
    assert intake.promote(store, 1, "2026-11-06") == high
    assert status_of(store, low) == ["deferred"]


@pytest.mark.parametrize("per_day", [0, -1])
def test_a_budget_of_zero_or_less_is_off(per_day):
    store = memory_beads.MemoryBeads()
    ids = filed(store, 2)
    assert intake.promote(store, per_day, "2026-11-06") == []
    assert status_of(store, ids) == ["deferred"] * 2


def test_the_loop_looks_only_every_few_minutes_and_only_within_the_budget():
    store, said = memory_beads.MemoryBeads(), []
    filed(store, 5)
    t = 1_000_000.0
    last = intake.promote_if_due(store, 2, t, 0.0, said.append, lambda _: "2026-11-06")
    assert (last, len(store.ready()), len(said)) == (t, 2, 2)
    assert intake.promote_if_due(store, 2, t + intake.CHECK_EVERY - 1, last, said.append, lambda _: "2026-11-06") == last  # too soon
    last = intake.promote_if_due(store, 2, t + intake.CHECK_EVERY, last, said.append, lambda _: "2026-11-06")
    assert (len(store.ready()), len(said)) == (2, 2)  # the day's budget is spent
    assert intake.promote_if_due(store, 0, t + 86400, last, said.append, lambda _: "2026-11-06") == last  # off
    assert len(store.ready()) == 2
