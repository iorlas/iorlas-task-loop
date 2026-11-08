"""The dashboard's stray rows come from the reconcile sweep's rule: a claim with no live run, and whether its lease ended."""

from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tltestkit.case import Case

from tldash.readers.observed import strays_of
from tldash.views.slots import stray_rows
from tldash.views.world import ProjectIn

NOW = 1793318400.0  # 2026-10-30T00:00:00Z
ENDED, RUNNING = "2026-10-29T23:00:00Z", "2026-10-30T01:00:00Z"


def slot(i: str, name: str, status: str = "in_progress", who: str = "tl-x", ends: str = ENDED, **meta: str) -> Bead:
    return Bead(id=BeadId(i), title=f"slot h {name}", status=status, assignee=who, lease_expires_at=ends, labels=["slot"],
                metadata={"held_gen": "4", **meta})


class Strays(Case):
    def test_a_claimed_slot_with_no_live_run_is_a_stray_and_says_if_its_lease_ended(self):
        got = strays_of([], [slot("sb-1", "s1"), slot("sb-2", "s2", ends=RUNNING)], {}, NOW)
        assert [(s.ref, s.expired, s.gen) for s in got] == [("sb-1", True, 4), ("sb-2", False, 4)]
        assert got[0].why == "claimed by tl-x, no live run (lease ended)"

    def test_a_free_slot_and_a_held_slot_are_no_stray(self):
        got = strays_of([], [slot("sb-1", "s1", status="open", who=""), slot("sb-2", "s2", hold_until=str(int(NOW) + 60))], {}, NOW)
        assert got == []

    def test_a_bead_held_by_an_engine_actor_without_a_live_run_is_a_stray_a_hand_claim_is_not(self):
        beads = [Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", lease_expires_at=ENDED),
                 Bead(id=BeadId("a-2"), title="", status="in_progress", assignee="denis", lease_expires_at=ENDED)]
        assert [s.ref for s in strays_of(beads, [], {}, NOW)] == ["a-1"]

    def test_a_paused_open_bead_still_assigned_and_a_leaseless_claim_are_strays_ready_to_give_back(self):
        beads = [Bead(id=BeadId("a-1"), title="", status="open", assignee="tl-x", lease_expires_at=ENDED),
                 Bead(id=BeadId("a-2"), title="", status="in_progress", assignee="tl-x", lease_expires_at=""),
                 Bead(id=BeadId("a-3"), title="", status="in_progress", assignee="tl-x", lease_expires_at=RUNNING)]
        assert [(s.ref, s.expired) for s in strays_of(beads, [], {}, NOW)] == [("a-1", True), ("a-2", True), ("a-3", False)]

    def test_a_claim_inside_its_lease_whose_holder_went_on_to_another_bead_is_ready_to_give_back(self):
        beads = [Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", lease_expires_at=RUNNING)]
        got = strays_of(beads, [slot("sb-1", "s1", ends=RUNNING, held_bead="a-2")], {}, NOW)
        assert [(s.kind, s.ref, s.expired) for s in got] == [("bead", "a-1", True), ("slot", "sb-1", False)]

    def test_the_slots_shows_a_stray_bead_as_an_idle_row_with_its_why(self):
        beads = [Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", lease_expires_at=ENDED)]
        rows = stray_rows(ProjectIn(id="p", name="p", beads=beads, strays=strays_of(beads, [slot("sb-1", "s1")], {}, NOW)))
        assert [(r.name, r.state, r.idle_why) for r in rows] == [("a-1", "idle", "claimed by tl-x, no live run (lease ended)")]
