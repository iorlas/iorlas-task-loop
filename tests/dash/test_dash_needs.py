"""The needs-you list and the loop strip: one snapshot row per kind (bead, why, since), the stalled and absent loops, and the rules that
keep a row out (an ask, a closed bead, a second kind for the same bead)."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import T, bead

from taskloop.contracts.ask import Ask, AskOption
from taskloop.contracts.enums import AskClass, AskKind, AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import LoopState, QueueRow, Skip
from taskloop.contracts.parks import Park
from taskloop.contracts.reconcile import LOOP_ABSENT_S, LOOP_STALL_S
from taskloop.contracts.run import NetPause
from taskloop.contracts.snapshots import LaneStatus, NeedInput, StatusSnapshot
from taskloop_dash.readers.observed import strays_of
from taskloop_dash.views import snapshot
from taskloop_dash.views.world import ProjectIn, Seen, World

NOW = T + 36000


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def loop(queue=(), t=NOW - 20, started=NOW - 9000, bead=None):
    return LoopState(pid=7, started=started, t=t, repo="/r/p", version="0.1", code_dir="/c", actor="tl", queue=list(queue), bead=bead)


def row(b, skip=None, since=NOW - 500):
    return QueueRow(bead=b, prio=2, since=since, skip=skip, ahead=-1 if skip else 0)


def slot(name, **meta):
    return bead(f"s-{name}", f"slot box {name}", "open", labels=["slot"], metadata=meta)


def world(beads=(), slots=(), loops=(), events=(), asks=None, **kw):
    p = ProjectIn(id="p", name="p", beads=list(beads), slots=list(slots), loops=list(loops), events=list(events))
    return World(now=NOW, host="h", version="v", projects=[p], runs={}, asks=asks or {}, **kw)


def needs(w):
    return snapshot.build(w).needs


def one(w, kind):
    got = [n for n in needs(w) if n.kind == kind]
    assert len(got) == 1, got
    return got[0]


class Kinds(unittest.TestCase):
    def test_a_label_the_owner_must_clear_is_a_row_with_the_bead_what_it_needs_and_since_its_last_change(self):
        waits = (("needs-ac", "acceptance criteria"), ("needs-info", "information"), ("owner-taste", "taste"), ("owner-look", "look"))
        for label, words in waits:
            with self.subTest(label):
                b = bead("p-1", "Add bills", labels=[label], updated_at=iso(NOW - 3600))
                r = one(world([b], loops=[loop([row("p-1")])]), "label")
                self.assertEqual((r.bead, r.project, r.since, r.title), ("p-1", "p", NOW - 3600, "Add bills"))
                self.assertIn(words, r.why)

    def test_a_blocked_bead_says_the_reason_of_its_block_event_and_when(self):
        w = world([bead("p-2", "Pick format", "blocked", updated_at=iso(NOW - 100))],
                  events=[Seen(kind="block", t=NOW - 7000, bead="p-2", why="needs a human: pick the format"),
                          Seen(kind="block", t=NOW - 5000, bead="p-2", why="needs a human: later")])
        r = one(w, "block")
        self.assertEqual((r.bead, r.why, r.since), ("p-2", "needs a human: later", NOW - 5000))

    def test_a_blocked_bead_with_no_event_still_shows_and_says_so(self):
        r = one(world([bead("p-2", "x", "blocked", updated_at=iso(NOW - 100))]), "block")
        self.assertEqual((r.why, r.since), ("blocked, no reason recorded", NOW - 100))

    def test_a_parked_bead_the_loop_will_not_take_again_is_a_row_since_its_park_record(self):
        sk = Skip(why="ended on a question twice; change the bead", kind="parked")
        w = world([bead("p-3", "Weather")], loops=[loop([row("p-3", sk, since=NOW - 90)])],
                  parks={"p-3": Park(bead=BeadId("p-3"), hash="h", runs=2, run="r", t=NOW - 4000)})
        r = one(w, "parked")
        self.assertEqual((r.bead, r.why, r.since), ("p-3", "ended on a question twice; change the bead", NOW - 4000))

    def test_a_capped_bead_falls_back_to_when_the_queue_first_saw_it(self):
        r = one(world([bead("p-4", "Cap")], loops=[loop([row("p-4", Skip(why="3 runs", kind="capped"), since=NOW - 90)])]),
                "capped")
        self.assertEqual((r.bead, r.since), ("p-4", NOW - 90))

    def test_a_run_paused_for_the_network_is_a_row_since_the_pause(self):
        r = one(world([bead("p-5", "Net")], net_pauses={"p-5": NetPause(run="r", bead="p-5", t=NOW - 600)}), "paused")
        self.assertEqual((r.bead, r.why, r.since), ("p-5", "paused for the network", NOW - 600))

    def test_a_lane_that_is_out_and_what_delegate_needs_are_rows_with_their_reason(self):
        lane = LaneStatus(id="c", family="codex", out=True, out_until=NOW + 600, out_reason="usage limit")
        st = StatusSnapshot(at=NOW - 10, lanes=[lane],
                            needs_input=[NeedInput(what="log in to xai", why="token expired")])
        got = {n.why: n for n in needs(world(status=st))}
        self.assertEqual(got["lane codex is out: usage limit"].until, NOW + 600)
        self.assertEqual(got["delegate needs: log in to xai (token expired)"].since, NOW - 10)

    def test_a_held_slot_shows_who_why_until_when_and_since_its_hold_event(self):
        w = world(slots=[slot("a", hold_until=str(int(NOW) + 1800), held_by="denis", held_why="testing by hand")],
                  events=[Seen(kind="slot_hold", t=NOW - 300, slot="a", why="testing by hand", until=NOW + 1800)])
        r = one(w, "slot_held")
        self.assertEqual((r.why, r.since, r.until, r.bead), ("slot a: testing by hand", NOW - 300, NOW + 1800, None))

    def test_a_slot_the_loop_set_aside_is_told_from_one_a_person_holds(self):
        w = world(slots=[slot("b", hold_until=str(int(NOW) + 900), held_why="set aside by tl loop: 3 runs failed")],
                  events=[Seen(kind="slot_hold", t=NOW - 400, slot="b"), Seen(kind="slot_aside", t=NOW - 300, bead="p-1", slot="b")])
        r = one(w, "slot_aside")
        self.assertEqual((r.why, r.since), ("slot b: set aside by tl loop: 3 runs failed", NOW - 300))

    def test_a_hold_that_ended_is_no_row(self):
        self.assertEqual(needs(world(slots=[slot("a", hold_until=str(int(NOW) - 5))])), [])

    def test_a_slot_whose_last_setup_failed_is_a_row_until_a_setup_passes(self):
        bad = [Seen(kind="slot_setup", t=NOW - 800, slot="c", exit=2)]
        r = one(world(slots=[slot("c")], events=bad), "slot_setup")
        self.assertEqual((r.why, r.since), ("slot c: setup failed (exit 2)", NOW - 800))
        self.assertEqual(needs(world(slots=[slot("c")], events=[*bad, Seen(kind="slot_setup", t=NOW - 100, slot="c")])), [])

    def test_a_claim_nothing_runs_under_is_a_stray_row(self):
        b = bead("p-6", "Lost", "in_progress", assignee="tl-x", lease_expires_at=iso(NOW - 60))
        p = ProjectIn(id="p", name="p", beads=[b], strays=strays_of([b], [], {}, NOW))
        r = one(World(now=NOW, host="h", version="v", projects=[p], runs={}, asks={}), "stray")
        self.assertEqual((r.bead, r.why), ("p-6", "claimed by tl-x, no live run (lease ended)"))



class Rules(unittest.TestCase):
    def test_a_bead_with_an_open_ask_is_the_decisions_tab_not_this_list(self):
        a = Ask(id="p-1-1", n=1, bead=BeadId("p-1"), kind=AskKind.DECISION, ask_class=AskClass.OPEN_QUESTION, decision="d",
                run="r", t=NOW - 9,
                status=AskStatus.OPEN, options=[AskOption(label="a", consequence="c")])
        w = world([bead("p-1", "x", "blocked", labels=["needs-info"])], asks={"p-1": a})
        self.assertEqual(needs(w), [])

    def test_a_closed_bead_and_an_epic_are_no_row(self):
        done = bead("p-1", "x", "closed", labels=["needs-ac"])
        epic = bead("p-2", "e", labels=["needs-ac"], issue_type="epic")
        self.assertEqual(needs(world([done, epic])), [])

    def test_a_bead_is_listed_once_under_the_first_kind_that_names_it(self):
        w = world([bead("p-1", "x", "blocked", labels=["needs-ac"])], loops=[loop([row("p-1", Skip(why="y", kind="parked"))])])
        self.assertEqual([n.kind for n in needs(w)], ["label"])

    def test_rows_are_oldest_first_and_a_row_with_no_time_is_last(self):
        w = world([bead("p-1", "a", labels=["needs-ac"], updated_at=iso(NOW - 100)),
                   bead("p-2", "b", labels=["needs-ac"], updated_at=iso(NOW - 900))],
                  status=StatusSnapshot(at=NOW, lanes=[LaneStatus(id="c", out=True)]))
        self.assertEqual([(n.bead, n.kind) for n in needs(w)], [("p-2", "label"), ("p-1", "label"), (None, "paused")])


class Health(unittest.TestCase):
    def info(self, w):
        return snapshot.build(w).server.loops[0]

    def test_a_loop_with_ready_beads_and_no_event_for_the_stall_time_is_stalled(self):
        w = world([bead("p-1", "x")], loops=[loop([row("p-1")], started=NOW - 9000)],
                  events=[Seen(kind="claim", t=NOW - LOOP_STALL_S - 60, bead="p-0", repo="/r/p")])
        i = self.info(w)
        self.assertEqual((i.health, i.ready, i.quiet_since), ("stalled", 1, NOW - LOOP_STALL_S - 60))
        r = one(w, "stalled")
        self.assertEqual((r.bead, r.since), (None, NOW - LOOP_STALL_S - 60))
        self.assertIn("1 ready bead(s)", r.why)

    def test_an_event_inside_the_stall_time_a_running_bead_or_nothing_ready_is_no_stall(self):
        ev = [Seen(kind="claim", t=NOW - LOOP_STALL_S + 60)]
        quiet = [Seen(kind="claim", t=NOW - LOOP_STALL_S - 60)]
        for name, w in {
            "recent event": world([bead("p-1", "x")], loops=[loop([row("p-1")])], events=ev),
            "running bead": world([bead("p-1", "x")], loops=[loop([row("p-1")], bead="p-9")], events=quiet),
            "nothing ready": world([], loops=[loop([])], events=quiet),
            "all skipped": world([bead("p-1", "x")], loops=[loop([row("p-1", Skip(why="a", kind="label"))])], events=quiet),
        }.items():
            with self.subTest(name):
                self.assertEqual(self.info(w).health, "ok")

    def test_a_loop_that_just_started_is_not_stalled_before_it_has_had_the_time(self):
        w = world([bead("p-1", "x")], loops=[loop([row("p-1")], started=NOW - 100)], events=[Seen(kind="claim", t=NOW - 99999)])
        self.assertEqual(self.info(w).health, "ok")

    def test_ready_beads_and_no_loop_for_the_absent_time_is_the_noloop_finding(self):
        w = world([bead("p-1", "x")], loops=[loop(t=NOW - LOOP_ABSENT_S - 5)])
        i = self.info(w)
        self.assertEqual((i.health, i.running, i.ready), ("absent", False, 1))
        self.assertEqual(one(w, "absent").why, "1 ready bead(s) and no loop alive")

    def test_a_beat_inside_the_absent_time_or_no_ready_bead_is_not_absent(self):
        self.assertEqual(self.info(world([bead("p-1", "x")], loops=[loop(t=NOW - 200)])).health, "ok")
        self.assertEqual(self.info(world([bead("p-1", "x", labels=["needs-ac"])])).health, "ok")


if __name__ == "__main__":
    unittest.main()
