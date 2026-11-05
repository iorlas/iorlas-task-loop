"""The v2 Snapshot and BeadDetail built from recorded typed logs, asks, loop state and bd fakes: strict decode, the key facts, the
version that moves exactly when a field does, the trims."""

import dataclasses
import os
import sys
import time
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.checks import res
from support.dashlogs import RunScript, T, bead
from support.narrow import must

from taskloop.contracts import wire
from taskloop.contracts.ask import Ask, AskOption
from taskloop.contracts.bead import Comment, Dep
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.dash import BeadDetail, CheckCount, Column, Marker, Snapshot
from taskloop.contracts.delegate import LiveCmdEnd, LiveCmdStart, LiveTokens
from taskloop.contracts.enums import AskClass, AskKind, AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.log import RunStart
from taskloop.contracts.loop import LoopState, QueueRow, Skip
from taskloop.contracts.parks import Park
from taskloop_dash.views import bead_detail, snapshot
from taskloop_dash.views.board import Board, review_of
from taskloop_dash.views.world import LookItem, ProjectIn, World

NOW = T + 3600


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def ask(bead_id, status=AskStatus.OPEN):
    return Ask(
        id=f"{bead_id}-1",
        n=1,
        bead=bead_id,
        kind=AskKind.DECISION,
        ask_class=AskClass.OPEN_QUESTION,
        decision="Which bills are weekly?",
        run="r",
        t=NOW - 900,
        status=status,
        tried=["read the design doc"],
        why="the bead and the doc disagree",
        options=[
            AskOption(label="Rent weekly", consequence="matches real life", recommended=True),
            AskOption(label="All weekly", consequence="simplest"),
        ],
    )


def loop(t, queue=()):
    return LoopState(pid=7, started=NOW - 9000, t=t, repo="/r/lifesim", version="0.1", code_dir="/c", actor="tl", queue=list(queue))


def slot_bead(name, status="open", **meta):
    return bead(f"s-{name}", f"slot box {name}", status, labels=["slot"], assignee="tl-x" if status != "open" else "", metadata=meta)


class Case(Case):
    def test_board_row_and_drawer_card_carry_the_persisted_retry_time(self):
        w = self.world()
        w = dataclasses.replace(
            w,
            parks={
                "b-parked": Park(
                    bead=BeadId("b-parked"),
                    hash="h",
                    runs=0,
                    run="r",
                    t=NOW,
                    reason="no_lane",
                    permanence="transient",
                    retry_at=NOW + 60,
                    attempts={"no_lane": 1},
                )
            },
        )
        p = w.projects[0]
        b = next(b for b in p.beads if b.id == "b-parked")
        assert Board(w).card(p, b, {}).retry_at == NOW + 60

    def setup_method(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def teardown_method(self):
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()

    def world(self, now=NOW, lost=False):
        runs = {
            "b-run": [
                RunScript("b-run", slot="a", at=3000)
                .step("plan", 300, 20_000, "OC Go")
                .step("write", 200, 30_000, text="write 1: clamp mood", end=False)
                .beat()
                .run(now, lost=lost)
            ],
            "b-ask": [RunScript("b-ask", slot="b", at=100).step("plan", 100, 1).close("parked", "needs_human").run(now)],
            "b-parked": [
                RunScript("b-parked", slot="c", at=200).step("write", 100, 1, "Codex").close("parked", "lane_out", "codex ran out").run(now)
            ],
            "b-done": [
                RunScript("b-done", slot="b", at=300)
                .step("plan", 100, 10, "OC Go")
                .step("write", 100, 20_000)
                .step("land", 10)
                .close("landed")
                .run(now)
            ],
            "b-look": [RunScript("b-look", slot="b", at=400).step("write", 100, 5, "OC Go").step("look", 10).close("landed").run(now)],
        }
        deps = [Dep(id="b-run", type="blocks"), Dep(id="e-1", type="parent-child")]
        beads = [
            bead("e-1", "Dashboard v2", issue_type="epic"),
            bead("b-run", "Clamp mood", "in_progress", parent="e-1", assignee="tl-a", priority=1),
            bead("b-ask", "Bills", parent="e-1"),
            bead("b-parked", "Weather tick", parent="e-1"),
            bead("b-ready", "Next up", parent="e-1", priority=0),
            bead("b-blocked", "After clamp", dependencies=deps, priority=3),
            bead("b-done", "Landed today", "closed", parent="e-1", closed_at=iso(NOW - 600), close_reason="landed abc"),
            bead("b-old", "Landed long ago", "closed", closed_at=iso(NOW - 3 * 86400)),
            bead("b-look", "Quit dialog", "closed", closed_at=iso(NOW - 500)),
            bead("l-1", "looks", labels=["owner-look"]),
        ]
        p = ProjectIn(
            id="lifesim",
            name="lifesim",
            beads=beads,
            slots=[
                slot_bead("a", "in_progress"),
                slot_bead("b"),
                slot_bead("c", hold_until=str(NOW + 600), held_by="denis", held_why="testing by hand"),
            ],
            loops=[
                loop(NOW - 30, [QueueRow(bead="b-ready", prio=0, since=NOW - 100, skip=Skip(why="codex out until 14:00", kind="lane"))])
            ],
            looks=[
                LookItem(
                    bead="b-look",
                    title="4 screens of the quit dialog",
                    artifacts=("/api/look-shot?repo=lifesim&path=a.png", "/api/look-shot?repo=lifesim&path=b.png"),
                )
            ],
        )
        return World(now=now, host="box", version="v1", projects=[p], runs={(p.id, b): rs for b, rs in runs.items()},
                     asks={(p.id, "b-ask"): ask("b-ask")})

    def snap(self, **kw):
        return snapshot.build(self.world(**kw))

    def card(self, snap, id):
        return next(c for c in snap.beads if c.id == id)


class Cards(Case):
    def test_the_card_carries_the_review_mode_of_the_newest_run(self):
        run = RunScript("b-run", slot="a", at=T).step("write", 100, 1, "Codex").run(T + 1)
        run = dataclasses.replace(run, start=RunStart(worktree="/w", review="off"))
        assert (review_of(run), review_of(None)) == ("off", None)

    def test_strict_decode_round_trips(self):
        s = self.snap()
        assert wire.load(Snapshot, wire.dump(s)) == s

    def test_columns_and_markers_of_every_bead(self):
        s = self.snap()
        got = {c.id: (c.column, c.marker) for c in s.beads}
        assert got == {
                "b-run": (Column.WORKING, Marker.RUN),
                "b-ask": (Column.QUESTIONS, Marker.ASK),
                "b-parked": (Column.BACKLOG, Marker.PARKED),
                "b-ready": (Column.BACKLOG, Marker.READY),
                "b-blocked": (Column.BACKLOG, Marker.BLOCKED),
                "b-done": (Column.DONE, Marker.DONE),
                "b-look": (Column.LOOK, Marker.LOOK),
            }

    def test_what_the_loop_runs_and_the_trims_leave_out(self):
        s = self.snap()
        ids = {c.id for c in s.beads}
        assert "b-old" not in ids  # closed before local midnight
        assert "e-1" not in ids  # an epic is a header, not a card
        assert "l-1" not in ids  # the look bead is the loop's own
        assert s.backlog_more == 0

    def test_a_running_card(self):
        c = self.card(self.snap(), "b-run")
        assert (c.status, c.tone, c.slot, c.lane, c.epic, c.t) == ("write 1: clamp mood", "run", "a", "OC Go", "e-1", T + 3000)
        assert [(d.phase.value, d.state) for d in c.dots][:3] == [("plan", "done"), ("write", "live"), ("test", "todo")]
        assert (c.totals.secs, c.totals.tokens) == (500, 50_000)

    def test_ask_look_parked_and_blocked_cards(self):
        s = self.snap()
        assert (self.card(s, "b-ask").status, self.card(s, "b-ask").tone) == ("Which bills are weekly?", "you")
        assert self.card(s, "b-look").shots == 0
        assert (self.card(s, "b-look").status, self.card(s, "b-look").tone) == ("waiting for your look", "you")
        parked = self.card(s, "b-parked")
        assert (parked.status, parked.slot, parked.t) == ("codex ran out", None, T + 300)  # a parked bead holds no slot
        blocked = self.card(s, "b-blocked")
        assert (blocked.status, blocked.needs) == ("waits for b-run", ["b-run"])
        assert self.card(s, "b-done").status == "landed abc"

    def test_a_ready_bead_no_loop_takes_says_why_only_while_a_loop_runs(self):
        assert self.card(self.snap(), "b-ready").waits_why == "codex out until 14:00"
        w = self.world()
        p = dataclasses.replace(w.projects[0], loops=[loop(NOW - 10_000, w.projects[0].loops[0].queue)])
        s = snapshot.build(dataclasses.replace(w, projects=[p]))
        assert self.card(s, "b-ready").waits_why == ""
        assert not s.server.loops[0].running
        assert s.server.loops[0].last_activity == NOW - 10_000

    def test_a_crashed_run_reads_exited(self):
        s = snapshot.build(self.world(now=NOW + 10_000, lost=True))  # the live run's process is gone: the reconciler marked it lost
        c = self.card(s, "b-run")
        assert (c.marker, c.tone) == (Marker.EXITED, "bad")
        assert c.status == "the run is lost: its process is gone and it recorded no end"

    def test_backlog_is_ordered_by_priority_and_capped(self):
        w = self.world()
        many = [bead(f"x-{i:03d}", f"t{i}", priority=3) for i in range(205)]
        p = dataclasses.replace(w.projects[0], beads=[*w.projects[0].beads, *many])
        s = snapshot.build(dataclasses.replace(w, projects=[p]))
        backlog = [c.id for c in s.beads if c.column is Column.BACKLOG]
        assert (len(backlog), s.backlog_more) == (200, 8)  # 3 real backlog beads + 205
        assert backlog[0] == "b-ready"  # priority 0 first

    def test_needs_never_name_a_bead_the_snapshot_trimmed(self):
        w = self.world()
        blocked = bead("x-1", "blocked by an epic", dependencies=[Dep(id="e-1", type="blocks")])
        gone = dataclasses.replace(w.projects[0], beads=[*w.projects[0].beads, blocked])
        s = snapshot.build(dataclasses.replace(w, projects=[gone]))
        assert self.card(s, "x-1").needs == []  # e-1 is an epic: no card, so no id


class Parts(Case):
    def test_only_typed_epics_include_childless_epics_and_exclude_task_parents(self):
        p = ProjectIn(id="p", name="p", beads=[
            bead("task-parent", issue_type="task"), bead("task-child", parent="task-parent"),
            bead("epic-empty", issue_type="epic"), bead("epic-closed", issue_type="epic", status="closed"),
        ])
        assert [(e.id, e.open, e.total) for e in snapshot.epics_of(p)] == [("epic-empty", True, 0), ("epic-closed", False, 0)]

    def test_only_an_open_epic_with_an_open_child_is_open(self):
        p = ProjectIn(
            id="p",
            name="p",
            beads=[
                bead("closed", status="closed", issue_type="epic"),
                bead("empty", issue_type="epic"),
                bead("active", issue_type="epic"),
                bead("a", parent="closed"),
                bead("b", parent="empty", status="closed"),
                bead("c", parent="active"),
            ],
        )
        assert {e.id: e.open for e in snapshot.epics_of(p)} == {"closed": False, "empty": False, "active": True}

    def test_epics_roll_up_their_children(self):
        (e,) = self.snap().epics
        assert (e.id, e.title, e.done, e.total) == ("e-1", "Dashboard v2", 1, 5)  # b-done closed; b-run, b-ask, b-parked, b-ready open

    def test_slots_held_running_free(self):
        s = {x.id: x for x in self.snap().slots}
        assert (s["a"].state, s["a"].bead, s["a"].lane, s["a"].t) == ("running", "b-run", "OC Go", T + 3000)
        assert (s["b"].state, s["b"].bead) == ("free", None)
        assert s["b"].lane == "OC Go"  # the lane of the slot's last call
        assert (s["c"].state, s["c"].idle_why) == ("held", "held by denis: testing by hand")

    def test_pieces_asks_and_server(self):
        s = self.snap()
        assert {p.bead for p in s.pieces} == {"b-run", "b-ask", "b-parked", "b-done", "b-look"}
        assert {(a.bead, a.source) for a in s.asks} == {("b-ask", "ask"), ("b-look", "look")}
        a = next(x for x in s.asks if x.source == "ask")
        assert (
            ([o.label for o in a.options], a.options[0].recommended, a.tried, a.why)
            == (["Rent weekly", "All weekly"], True, ["read the design doc"], "the bead and the doc disagree")
        )
        assert (
            next(x for x in s.asks if x.source == "look").artifacts
            == ["/api/look-shot?repo=lifesim&path=a.png", "/api/look-shot?repo=lifesim&path=b.png"]
        )
        assert (s.server.version, s.server.host, s.projects[0].id) == ("v1", "box", "lifesim")
        assert (s.ledger, s.adrs, s.lanes) == ([], [], [])  # no source yet

    def test_pieces_outside_the_floor_window_are_dropped(self):
        assert len(self.snap().pieces) == 5
        assert self.snap(now=NOW + 9 * 3600).pieces == []  # every run ended more than 8 h ago


class Version(Case):
    def test_an_unchanged_world_keeps_its_version_whatever_the_clock_says(self):
        a, b = self.snap(), self.snap(now=NOW + 60)
        assert a.version == b.version
        assert (a.t, b.t) == (NOW, NOW + 60)

    def test_a_changed_field_changes_it(self):
        w = self.world()
        runs = dict(w.runs)
        runs[("lifesim", "b-run")] = [
            RunScript("b-run", slot="a", at=3000)
            .step("plan", 300, 20_000, "OC Go")
            .step("write", 200, 30_000, text="write 1: clamp mood", end=False)
            .step("checks", 50, 1)
            .run(NOW)
        ]
        assert snapshot.build(dataclasses.replace(w, runs=runs)).version != snapshot.build(w).version


class Detail(Case):
    def detail(self, id, comments=(), events=()):
        w = self.world()
        p = w.projects[0]
        b = next(x for x in p.beads if x.id == id)
        return bead_detail.build(Board(w), p, b, comments, events)

    def test_strict_decode_and_the_card(self):
        d = self.detail("b-run")
        assert wire.load(BeadDetail, wire.dump(d)) == d
        assert d.card == self.card(self.snap(), "b-run")

    def test_text_comments_and_links(self):
        c = Comment(author="denis", text="keep the old save format", created_at=iso(NOW - 120))
        d = self.detail("b-run", [c])
        assert ([(m.who, m.md, m.t) for m in d.comments]) == [("denis", "keep the old save format", NOW - 120)]
        assert self.detail("b-blocked").waits_for == ["b-run"]
        assert d.unblocks == ["b-blocked"]
        assert self.detail("b-done").description == ""

    def test_passes_with_cells_and_the_live_box(self):
        d = self.detail(
            "b-run",
            events=[
                LiveCmdStart(t=1.0, id="k1", text="codex exec write"),
                LiveCmdEnd(t=2.0, id="k1"),
                LiveCmdStart(t=3.0, id="k2", text="pytest -q"),
                LiveTokens(t=4.0, in_=100_000, cached=60_000, out=5_000),
            ],
        )
        (p,) = d.passes
        assert (p.n, p.end, p.resumed) == (1, "", None)
        assert {c.phase.value: c.state for c in p.cells}["write"] == "live"
        box = must(d.live)
        assert (box.kind, box.phase.value, box.pass_n, box.cmd, box.tokens, box.t) == ("run", "write", 1, "pytest -q", 45_000, T + 3300)
        assert box.checks is None

    def test_the_live_box_counts_unverified_checks_apart_from_passed_and_failed(self):
        run = CheckRun(round=1, results=[res("a", 0), res("b", 1), res("c", 86, status="unverified")])
        script = (
            RunScript("b-run", slot="a", at=3000)
            .step("checks", 50, 1, end=False)
            .wait(500)
            .add("checks", node_id="n1", run={k: v for k, v in wire.dump(run).items() if k != "v"})
            .beat()
        )
        w = self.world()
        d = bead_detail.build(
            Board(dataclasses.replace(w, runs={**w.runs, ("lifesim", "b-run"): [script.run(NOW)]})),
            w.projects[0],
            next(x for x in w.projects[0].beads if x.id == "b-run"),
            (),
            (),
        )
        box = must(d.live)
        assert must(box.checks) == CheckCount(passed=1, failed=1, unverified=1, total=3)

    def test_an_ended_run_has_no_live_box_and_a_crashed_one_reads_exited(self):
        assert self.detail("b-done").live is None
        w = dataclasses.replace(self.world(now=NOW + 10_000, lost=True))
        p = w.projects[0]
        d = bead_detail.build(Board(w), p, next(x for x in p.beads if x.id == "b-run"), [], [])
        assert (must(d.live).kind, must(d.live).why) == ("exited", "the run is lost: its process is gone and it recorded no end")

    def test_ask_and_look_ride_with_the_bead(self):
        assert must(self.detail("b-ask").ask).question == "Which bills are weekly?"
        look = must(self.detail("b-look").ask)
        assert (look.source, look.id, len(look.artifacts)) == ("look", "b-look-look", 2)
        assert self.detail("b-run").ask is None

    def test_the_drawers_artifacts_come_from_the_store_never_from_the_runs_artifact_records(self):
        w = self.world()
        s = RunScript("b-look", slot="b", at=400).step("write", 100, 5, "OC Go").step("look", 10)
        s = s.artifacts(2, "look", "shot-1.png").close("landed")
        w = dataclasses.replace(w, runs={**w.runs, ("lifesim", "b-look"): [s.run(NOW)]})
        p = w.projects[0]
        d = bead_detail.build(Board(w), p, next(x for x in p.beads if x.id == "b-look"), [], [])
        assert d.artifacts == []  # the store listing (tests/dash/test_dash_artifacts.py) is the one source
        assert self.card(snapshot.build(w), "b-look").shots == 1  # the card counts the run's records, touching no file


class EngineFacts(Case):
    """Backend item 5: the card's assumptions and stuck marker, the drawer's messages and stuck live box, from typed records."""

    def stuck_world(self):
        w = self.world()
        s = (
            RunScript("b-run", slot="a", at=3000)
            .step("plan", 300, 20_000, "OC Go")
            .add("assumed", step="n1", text="no Windows PC")
            .add("said", step="n1", who="engine", text="Plan (engine): 1 stage")
            .step("write", 200, 30_000, text="write 1: clamp mood", end=False)
        )
        s.add("stuck", why="silent", step="write", since=s.t, limit_s=1800.0).beat()
        return dataclasses.replace(w, runs={**w.runs, ("lifesim", "b-run"): [s.run(NOW)]})

    def test_the_card_counts_assumptions_and_reads_stuck(self):
        c = self.card(snapshot.build(self.stuck_world()), "b-run")
        assert (c.assumptions, c.marker, c.tone, c.status) == (1, Marker.STUCK, "bad", "stuck: silent past 30m in write")
        assert self.card(self.snap(), "b-run").assumptions == 0

    def test_the_drawer_has_the_messages_and_the_stuck_box(self):
        w = self.stuck_world()
        p = w.projects[0]
        d = bead_detail.build(Board(w), p, next(x for x in p.beads if x.id == "b-run"), [], [])
        (ps,) = d.passes
        assert (ps.end, [m.md for m in ps.messages]) == ("stuck", ["stuck: silent past 30m in write", "Plan (engine): 1 stage"])
        assert {c.phase.value: c.last for c in ps.cells}["plan"] == "Plan (engine): 1 stage"
        box = must(d.live)
        assert (box.kind, box.phase.value, box.why, box.t) == ("stuck", "write", "stuck: silent past 30m in write", T + 3500)
