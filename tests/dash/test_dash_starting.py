"""A slot remains visible between its claim and the engine's first manifest."""

from support.case import Case
from support.dashlogs import RunScript, T, bead

from taskloop_dash.views.floor import slot_of
from taskloop_dash.views.snapshot import build
from taskloop_dash.views.world import ProjectIn, World
from tlkernel.dash import Column
from tlkernel.events import Claim, SlotSetup, SlotTake, Stage
from tlkernel.ids import BeadId
from tlkernel.reconcile import Stray

NOW = T + 120
CLAIMED = "2027-01-15T08:00:00Z"  # T


def slot(**metadata):
    return bead("slot-a", "slot host a", "in_progress", assignee="tl-loop", updated_at=CLAIMED,
                metadata=metadata)


def project(target=None, events=()):
    return ProjectIn(id="p", name="p", beads=[target or bead("p-1", "Starting work", "in_progress")], events=events)


class Starting(Case):
    def test_claimed_slot_with_known_work_starts_at_the_claim_time(self):
        for status in ("open", "in_progress"):
            with self.subTest(status=status):
                got = slot_of(project(bead("p-1", status=status)), slot(held_bead="p-1"), {}, NOW)
                assert (got.state, got.bead, got.t, got.idle_why) == ("starting", "p-1", T, "starting p-1")

    def test_held_since_is_used_and_invalid_metadata_falls_back_to_updated(self):
        for since, expected in ((T + 10, T + 10), ("2027-01-15T08:00:10Z", T + 10), ("invalid", T)):
            with self.subTest(since=since):
                assert slot_of(project(), slot(held_bead="p-1", held_since=since), {}, NOW).t == expected

    def test_running_wins_when_the_live_manifest_appears(self):
        run = RunScript("p-1", slot="a", at=60).step("write", 10, lane="codex", tokens=1, end=False).run(NOW)
        got = slot_of(project(), slot(held_bead="p-1"), {"p-1": [run]}, NOW)
        assert (got.state, got.bead, got.t, got.lane) == ("running", "p-1", T + 60, "codex")

    def test_missing_unknown_closed_and_other_status_targets_stay_idle(self):
        for target, metadata in ((bead("p-1"), {}), (bead("p-2"), {"held_bead": "p-1"}),
                                 (bead("p-1", status="closed"), {"held_bead": "p-1"}),
                                 (bead("p-1", status="blocked"), {"held_bead": "p-1"})):
            with self.subTest(target=target, metadata=metadata):
                got = slot_of(project(target), slot(**metadata), {}, NOW)
                assert (got.state, got.bead, got.idle_why) == ("idle", None, "claimed by tl-loop, no live run")

    def test_person_hold_and_open_slot_keep_their_states(self):
        held = slot(held_bead="p-1", hold_until=NOW + 60, held_by="owner")
        assert slot_of(project(), held, {}, NOW).state == "held"
        assert slot_of(project(), held.replace(status="open", metadata={"held_bead": "p-1"}), {}, NOW).state == "free"

    def test_startup_uses_only_this_claims_bead_and_slot_events(self):
        events = [SlotSetup(t=T - 10, slot="a"), SlotTake(t=T, slot="a"),
                  Claim(t=T + 1, slot="a", bead="p-1"), SlotSetup(t=T + 5, slot="b"),
                  SlotSetup(t=T + 10, slot="a"), Stage(t=T + 20, bead="p-2", step="rebase"),
                  Stage(t=T + 30, bead="p-1", step="rebase"), SlotSetup(t=NOW + 1, slot="a")]
        got = slot_of(project(events=events), slot(held_bead="p-1"), {}, NOW)
        assert got.startup == "claimed · setup · rebase"
        assert slot_of(project(), slot(held_bead="p-1"), {}, NOW).startup == ""

    def test_snapshot_keeps_claimed_bead_in_working_before_any_run(self):
        p = project()
        p = ProjectIn(id=p.id, name=p.name, beads=p.beads, slots=[slot(held_bead="p-1")])
        snap = build(World(now=NOW, host="host", version="test", projects=[p], runs={}, asks={}))
        assert snap.slots[0].state == "starting"
        assert snap.beads[0].column == Column.WORKING


class Abandoned(Case):
    def snap(self, expired):
        p = project()
        p = ProjectIn(id=p.id, name=p.name, beads=p.beads,
                      strays=[Stray("bead", BeadId("p-1"), "p-1", "tl-loop", 1, expired)])
        return build(World(now=NOW, host="host", version="test", projects=[p], runs={}, asks={})).beads[0]

    def test_a_claim_with_an_ended_lease_and_no_run_is_not_running(self):
        card = self.snap(True)
        assert (card.column, card.marker.value) == (Column.WORKING, "exited")
        assert card.status == "claimed by tl-loop, no live run (lease ended)"

    def test_a_claim_inside_its_lease_is_still_starting(self):
        assert self.snap(False).marker.value == "run"


class Stalled(Case):
    """Past the startup lease a claim with no run is not RUN: the card says the start stalled (the F03 board half)."""

    def card(self, age):
        p = project()
        p = ProjectIn(id=p.id, name=p.name, beads=p.beads, slots=[slot(held_bead="p-1")])
        return build(World(now=T + age, host="host", version="test", projects=[p], runs={}, asks={})).beads[0]

    def test_inside_the_lease_the_claim_reads_as_running(self):
        c = self.card(120)
        assert c.marker.value == "run" and c.column == Column.WORKING

    def test_past_the_lease_it_reads_exited_with_the_stalled_reason(self):
        c = self.card(700)
        assert c.marker.value == "exited" and c.column == Column.WORKING
        assert c.status.startswith("start stalled: no run 11 min")
