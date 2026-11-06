"""INTAKE (tl-7i9k.19): agent-filed follow-ups wait as `deferred` with the label `from-review`; at most K a day are promoted to open."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads

from taskloop.app.asks import deferral as intake
from taskloop.contracts.ports import BeadQuery, NewBead


def filed(store, n, priority=None):
    ids = []
    for i in range(n):
        made = store.create(NewBead(title=f"f{i}", description="d", labels=[intake.FROM_REVIEW], priority=priority))
        intake.defer(store, made)
        ids.append(made)
    return ids


def status_of(store, ids):
    return [b.status for b in (store.show(i) for i in ids) if b is not None]


def test_defer_leaves_the_bead_labelled_and_out_of_ready():
    store = FakeBeads()
    (made,) = filed(store, 1)
    got = store.show(made)
    assert got is not None and got.status == "deferred" and intake.FROM_REVIEW in got.labels
    assert store.ready() == []


def test_k_a_day_are_promoted_and_the_rest_wait():
    store = FakeBeads()
    ids = filed(store, 5)
    assert intake.promote(store, 3, "2026-11-06") == ids[:3]
    assert status_of(store, ids) == ["open"] * 3 + ["deferred"] * 2
    assert intake.promote(store, 3, "2026-11-06") == []  # the day's budget is spent
    assert intake.promote(store, 3, "2026-11-07") == ids[3:]  # the next day takes the rest


def test_a_promoted_bead_that_closed_the_same_day_still_counts():
    store = FakeBeads()
    ids = filed(store, 4)
    for made in intake.promote(store, 2, "2026-11-06"):
        store.close(made, "done")
    assert intake.promote(store, 2, "2026-11-06") == []
    assert len(store.find(BeadQuery(label=intake.PROMOTED + "2026-11-06", include_closed=True))) == 2
    assert status_of(store, ids[2:]) == ["deferred", "deferred"]


def test_higher_priority_goes_first_and_off_promotes_nothing():
    store = FakeBeads()
    low = filed(store, 1, priority=3)
    high = filed(store, 1, priority=1)
    assert intake.promote(store, 0, "2026-11-06") == []
    assert intake.promote(store, 1, "2026-11-06") == high
    assert status_of(store, low) == ["deferred"]


@pytest.mark.parametrize("per_day", [0, -1])
def test_a_budget_of_zero_or_less_is_off(per_day):
    store = FakeBeads()
    ids = filed(store, 2)
    assert intake.promote(store, per_day, "2026-11-06") == []
    assert status_of(store, ids) == ["deferred"] * 2


def test_the_loop_looks_only_every_few_minutes_and_only_within_the_budget():
    store, said = FakeBeads(), []
    filed(store, 5)
    t = 1_000_000.0
    last = intake.promote_if_due(store, 2, t, 0.0, said.append)
    assert (last, len(store.ready()), len(said)) == (t, 2, 2)
    assert intake.promote_if_due(store, 2, t + intake.CHECK_EVERY - 1, last, said.append) == last  # too soon
    last = intake.promote_if_due(store, 2, t + intake.CHECK_EVERY, last, said.append)
    assert (len(store.ready()), len(said)) == (2, 2)  # the day's budget is spent
    assert intake.promote_if_due(store, 0, t + 86400, last, said.append) == last  # off
    assert len(store.ready()) == 2
