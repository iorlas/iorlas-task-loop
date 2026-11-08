"""Occupancy precedence, lease boundaries and location names on fake locks."""
from typing import NamedTuple

import pytest
from tlkernel.bead import Bead
from tlkernel.ids import BeadId

from tlareas.policy import occupancy

STAMP = "2026-11-08T12:00:00Z"


class Lock(NamedTuple):
    __test__ = False

    bead: str
    slot: str = ""
    alive: bool = True


@pytest.mark.parametrize("held,status,expires,counts", [
    ("x-1", "in_progress", "", True),
    ("x-1", "in_progress", "2026-11-08T11:59:59Z", False),
    ("x-1", "in_progress", STAMP, True),
    ("x-1", "in_progress", "2026-11-08T12:00:01Z", True),
    ("x-1", "open", "", False),
    ("x-1", "closed", "", False),
    ("--invalid", "in_progress", "", False),
    (None, "in_progress", "", False),
])
def test_held_slot_requires_a_bead_in_progress_and_unexpired_lease(held, status, expires, counts):
    bead = Bead(id=BeadId("sl-1"), title="slot for repo s1", status=status,
                metadata={"held_bead": held}, lease_expires_at=expires)
    assert occupancy([bead], [], lambda wt: None, lambda lock: True, STAMP) == ({"x-1": "s1"} if counts else {})


@pytest.mark.parametrize("lock,expected", [
    (Lock("x-1", "s2"), {"x-1": "s2"}),
    (Lock("x-1"), {"x-1": "hand-tree"}),
    (Lock("x-1", alive=False), {}),
    (Lock("--invalid"), {}),
    (None, {}),
])
def test_live_lock_requires_a_bead_and_uses_slot_or_worktree_name(lock, expected):
    assert occupancy([], ["repo/hand-tree/"], lambda wt: lock, lambda held: held.alive, STAMP) == expected


def test_slot_beads_win_and_dictionary_insertion_order_is_preserved():
    beads = [Bead(id=BeadId("sl-1"), title="slot s1", status="in_progress", metadata={"held_bead": "x-2"}),
             Bead(id=BeadId("sl-2"), title="slot s2", status="in_progress", metadata={"held_bead": "x-1"})]
    locks = {"repo/s3": Lock("x-1", "s3"), "repo/hand": Lock("x-3"), "repo/s4": Lock("x-3", "s4")}
    got = occupancy(beads, iter(locks), locks.get, lambda held: held.alive, STAMP)
    assert list(got.items()) == [("x-2", "s1"), ("x-1", "s2"), ("x-3", "hand")]
