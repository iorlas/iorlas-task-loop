"""A claimed slot is `setup` (starting) only within the startup lease of its claim; past it the start stalled."""

import pytest
from support.dashlogs import T, bead

from taskloop.contracts.slottable import STARTUP_LEASE_S, build_slot_table


def state_at(age: float, since: object, dir_exists: bool = True) -> tuple[str, str]:
    slot = bead("s-a", "slot host s1", "in_progress", assignee="tl-loop", metadata={"held_bead": "p-1", "held_since": since})
    table = build_slot_table([slot], 1, {}, ["s1"] if dir_exists else [], T + age, "worktree", targets={"p-1"})
    return table.slots[0].state, table.slots[0].idle_why


@pytest.mark.parametrize(("age", "state"), [(0, "setup"), (STARTUP_LEASE_S, "setup"), (STARTUP_LEASE_S + 1, "claimed")])
@pytest.mark.parametrize("since", [T, str(T), "2027-01-15T08:00:00Z"])
def test_the_lease_bounds_starting_in_both_claim_time_formats(age: float, state: str, since: object) -> None:
    assert state_at(age, since)[0] == state


def test_a_stalled_start_says_so_with_its_age() -> None:
    assert state_at(11 * 60 + 5, T) == ("claimed", "start stalled: no run 11 min after claiming p-1")


def test_a_stalled_start_without_its_folder_is_dead() -> None:
    assert state_at(STARTUP_LEASE_S + 1, T, dir_exists=False)[0] == "dead"


@pytest.mark.parametrize("since", ["", "not a time"])
def test_an_unknown_claim_time_reads_as_starting(since: str) -> None:
    assert state_at(10**6, since)[0] == "setup"
