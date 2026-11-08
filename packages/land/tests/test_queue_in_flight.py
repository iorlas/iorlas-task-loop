"""Gates in flight (merge-queue.md section 6): grow by 1 on a merge, halve on an own failure or conflict eject, floor 1, cap, a flake or an
infra stop never shrinks, a wasted ratio over 0.5 holds the growth; the state is per repo."""
import pytest

from tlland.domain.queue_in_flight import WASTE_LAST_MERGES, Account, Cause, Event, in_flight, wasted_ratio
from tlland.queue import InFlight


@pytest.mark.parametrize("current, event, cap, ratio, want", [
    (1, Event.MERGED, 4, 0.0, 2),  # grow
    (3, Event.MERGED, 4, 0.0, 4),
    (4, Event.MERGED, 4, 0.0, 4),  # cap
    (2, Event.MERGED, 1, 0.0, 1),  # a cap under the floor is the floor
    (3, Event.MERGED, 4, 0.51, 3),  # waste holds the growth
    (3, Event.MERGED, 4, 0.5, 4),  # at the threshold it still grows
    (4, Event.GATE_FAILED, 4, 0.0, 2),  # halve
    (3, Event.GATE_FAILED, 4, 0.0, 1),  # round down
    (4, Event.CONFLICT_EJECT, 4, 0.0, 2),
    (1, Event.GATE_FAILED, 4, 0.0, 1),  # floor
    (3, Event.FLAKE, 4, 0.0, 3),  # a flake does not shrink
    (3, Event.INFRA, 4, 0.0, 3),  # nor does an infra stop
    (4, Event.INFRA, 3, 0.0, 3),  # a lowered cap still applies
    (1, Event.MERGED, 4, 1.0, 1),  # held, never below the floor
])
def test_in_flight_table(current, event, cap, ratio, want):
    assert in_flight(current, event, cap=cap, ratio=ratio) == want


def test_the_ratio_is_wasted_over_all_gate_seconds_of_the_last_twenty_merges():
    assert wasted_ratio([]) == 0.0
    old = [Account(pr=i, useful_gate_s=1, wasted_gate_s=100, causes=(Cause.BASE_MOVED,)) for i in range(5)]
    recent = [Account(pr=100 + i, useful_gate_s=10) for i in range(WASTE_LAST_MERGES - 1)] + [
        Account(pr=200, useful_gate_s=10, wasted_gate_s=10, causes=(Cause.CULPRIT_AHEAD,))]
    assert wasted_ratio(old + recent) == pytest.approx(10 / 210)  # the five old ones fell out of the last twenty


def test_wasted_seconds_need_a_cause():
    with pytest.raises(ValueError, match="cause"):
        Account(pr=1, useful_gate_s=1, wasted_gate_s=5)


def test_a_queue_starts_at_one_grows_on_merges_and_halves_on_a_failure():
    q = InFlight(cap=4)
    assert q.current == 1
    assert [q.merged(n, 10) for n in (1, 2, 3, 4)] == [2, 3, 4, 4]
    assert q.happened(Event.GATE_FAILED) == 2
    assert q.happened(Event.FLAKE) == 2


def test_waste_since_the_last_merge_is_booked_on_the_next_merge_with_its_cause_and_holds_growth():
    q = InFlight()
    q.merged(1, 10)
    q.merged(2, 10)
    q.waste(40, Cause.CULPRIT_AHEAD)
    before = q.current
    assert q.merged(3, 10) == before  # 40 wasted of 70 total: over half, held
    assert q.accounts[-1].causes == (Cause.CULPRIT_AHEAD,) and q.accounts[-1].wasted_gate_s == 40
    assert q.pending_s == 0


def test_each_repo_has_its_own_state():
    a, b = InFlight(), InFlight()
    a.merged(1, 10)
    a.happened(Event.MERGED)
    a.happened(Event.GATE_FAILED)
    assert (a.current, b.current) == (1, 1) and len(b.accounts) == 0
    a.merged(2, 1)
    assert b.current == 1
