"""The ask records the page shows: the AskCard fields, the soft ask's marker, the ledger rows, the decisions in
force, the learning series, and POST /api/stick through Ports."""
import os
import sys
import time
from pathlib import Path

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from asks.dash_ports import answering
from support.dashes import make_dash
from support.dashlogs import T, bead
from support.fake_beads import FakeBeads
from support.memstores import fake_stores

from taskloop.app.asks import intake, raiser
from taskloop_dash.views import bead_detail, snapshot
from taskloop_dash.views.board import Board
from taskloop_dash.views.world import AdrIn, Landing, ProjectIn, World
from tlkernel import askspecs as specs
from tlkernel import wire
from tlkernel.adrs import AdrStore
from tlkernel.ask import SimilarRef, ThreadEntry
from tlkernel.askstore import AskStore
from tlkernel.bead import Bead
from tlkernel.dash import Column, Marker, OwnerCause, Result, Stick
from tlkernel.ids import BeadId, loop_key
from tlkernel.ledger import Adr
from tltestkit.narrow import must
from tltestkit.repos import write_repos

DAY = 86400.0
NOW = T + 20 * DAY
REPO = "/r/lifesim"
Q = "Which bills are weekly?"
OPTS = [{"label": "Rent weekly", "cost": "none", "answer": "rent weekly", "recommended": True},
        {"label": "All weekly", "cost": "a run", "answer": "all weekly", "recommended": False}]


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Case(Case):
    def setup_method(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(self.restore_tz)
        self.stores = fake_stores()
        self.asks = self.stores.asks
        self.beads = FakeBeads()
        for k in range(5):
            self.beads.beads[BeadId(f"b-{k}")] = Bead(id=BeadId(f"b-{k}"), title="x", status="blocked")
        self.verbs = intake.Intake(self.asks, self.beads, lambda: NOW - 3 * DAY, "denis", self.stores.adrs)

    def restore_tz(self):
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()

    def raise_(self, bead_id, now, question=Q, cause="decision", default="", adrs=None):
        return must(raiser.raise_ask(self.asks, specs.open_question(question, OPTS, cause, default), raiser.Asking(
            bead=bead_id, run="r", brief_hash="h", repo=REPO, title=bead_id, now=now), adrs)[0])

    def world(self, beads, adrs=(), landings=(), live=None):
        p = ProjectIn(id=loop_key(REPO), name="lifesim", beads=beads, adrs=list(adrs))
        live = live if live is not None else {a.bead: a for a in self.asks.live()}
        return World(now=NOW, host="box", version="v1", projects=[p], runs={}, asks={(p.id, b): a for b, a in live.items()},
                     ledger=self.asks.rows(), landings=list(landings))

    def snap(self, beads, **kw):
        return snapshot.build(self.world(beads, **kw))


class Cards(Case):
    def test_an_ask_card_carries_the_typed_fields_of_the_ask(self):
        key = self.raise_("b-0", T).key
        adr = self.stores.adrs(REPO).add(Adr(id="", n=0, repo=REPO, text="Rent is weekly", question=Q, answer="rent", ask="b-0-1",
                                             bead="b-0", key=key, t=NOW - 5 * DAY))
        a = self.raise_("b-1", NOW - DAY, cause="requirement", adrs=self.stores.adrs(REPO))
        assert a.similar == [SimilarRef(kind="adr", id=adr.id)]
        self.asks.put(a.replace(thread=[ThreadEntry(by="owner", t=NOW - 100, md="why?"),
                                                     ThreadEntry(by="helper", t=NOW - 90, md="because")]))
        beads = [bead("b-1", "Bills"), bead("b-2", "Done after", "closed", closed_at=iso(NOW - 3600)),
                 bead("b-3", "Done before", "closed", closed_at=iso(NOW - 5 * DAY))]
        asks = {x.bead: x for x in self.snap(beads, adrs=[AdrIn(adr, 2, NOW - 100)]).asks}
        card = asks["b-1"]
        assert (card.blocking, card.owner_cause, card.cause_by, card.default) == (True, OwnerCause.REQUIREMENT, "agent", "")
        assert [(m.by, m.md) for m in card.thread] == [("owner", "why?"), ("helper", "because")]
        assert (card.ask_backs, card.stale) == (1, 1)
        assert must(card.similar).answer == "Rent is weekly"
        assert (must(card.similar).bead, must(card.similar).t) == ("b-0", NOW - 5 * DAY)

    def test_an_ask_card_lists_its_artifacts_by_url(self):
        a = self.raise_("b-1", NOW - DAY)
        self.asks.put(a.replace(artifacts=["lifesim/b-1/run1/write-2/board.png", "not-an-id"]))
        card = {x.bead: x for x in self.snap([bead("b-1", "Bills")]).asks}["b-1"]
        assert len(card.artifacts) == 1
        url = card.artifacts[0]
        assert url.startswith("/api/artifact?") and "name=board.png" in url and "stage=write" in url

    def test_a_card_matches_a_past_answered_ask_when_no_decision_is_in_force(self):
        first = self.raise_("b-0", NOW - 9 * DAY)
        self.verbs.answer(BeadId("b-0"), "text", "rent weekly")
        a = self.raise_("b-1", NOW - DAY)
        assert a.similar == [SimilarRef(kind="ask", id=first.id)]
        card = self.snap([bead("b-1", "Bills")]).asks[0]
        assert (must(card.similar).bead, must(card.similar).answer, must(card.similar).question) == ("b-0", "rent weekly", Q)

    def test_the_owner_corrects_the_cause_and_the_card_shows_it(self):
        a = self.raise_("b-1", NOW - DAY, cause="process")
        assert self.verbs.cause(BeadId("b-1"), a.id, "environment") == ""
        card = self.snap([bead("b-1", "Bills")]).asks[0]
        assert (card.owner_cause, card.cause_by) == (OwnerCause.ENVIRONMENT, "owner")

    def test_a_soft_ask_marks_the_bead_without_moving_its_column_and_the_drawer_shows_it(self):
        a = self.raise_("b-1", NOW - DAY, default="went on with weekly rent")
        beads = [bead("b-1", "Bills", "in_progress", assignee="tl-a")]
        w = self.world(beads)
        s = snapshot.build(w)
        card = s.beads[0]
        assert (card.marker, card.column, card.tone) == (Marker.SOFT_ASK, Column.WORKING, "you")
        assert a.decision in card.status
        ask = s.asks[0]
        assert (ask.blocking, ask.default) == (False, "went on with weekly rent")
        detail = bead_detail.build(Board(w), w.projects[0], beads[0], [], [])
        assert must(detail.ask).id == a.id

    def test_a_blocking_ask_still_fills_the_questions_column(self):
        self.raise_("b-1", NOW - DAY)
        card = self.snap([bead("b-1", "Bills", "blocked")]).beads[0]
        assert (card.marker, card.column) == (Marker.ASK, Column.QUESTIONS)


class Ledger(Case):
    def test_rows_hold_open_soft_and_answered_asks_newest_first_with_cause_and_outcome(self):
        done = self.raise_("b-1", NOW - 6 * DAY, cause="requirement")
        self.verbs.answer(BeadId("b-1"), "text", "rent weekly")
        self.verbs.cause(BeadId("b-1"), done.id, "decision")
        self.asks.consume(BeadId("b-1"), NOW - 5 * DAY)
        self.asks.stuck(BeadId("b-1"), done.id, Stick.ONCE, "", NOW - 5 * DAY)
        hard = self.raise_("b-2", NOW - 2 * DAY)
        soft = self.raise_("b-3", NOW - DAY, default="weekly")
        gone = self.raise_("b-4", NOW - 3 * DAY)
        self.asks.withdraw(BeadId("b-4"), gone.id, "n/a", NOW)
        rows = self.snap([bead(b, b) for b in ("b-2", "b-3", "b-4")]).ledger
        assert [(r.ask, r.status) for r in rows] == [(soft.id, "open_soft"), (hard.id, "open"), (done.id, "answered")]
        old = rows[2]
        assert (
            (old.answer, old.outcome, old.cause, old.project, old.question, old.t)
            == ("rent weekly", Stick.ONCE, OwnerCause.DECISION, loop_key(REPO), Q, NOW - 6 * DAY)
        )
        assert (rows[0].outcome, rows[0].cause) == (None, OwnerCause.DECISION)

    def test_an_open_row_of_a_bead_the_snapshot_does_not_show_is_left_out_but_an_answered_one_stays(self):
        self.raise_("b-1", NOW - 6 * DAY)
        self.verbs.answer(BeadId("b-1"), "text", "x")
        self.raise_("b-2", NOW - DAY)
        assert [r.status for r in self.snap([bead("b-1", "x", "closed", closed_at=iso(NOW - 4 * DAY))]).ledger] == ["answered"]

    def test_the_snapshot_version_moves_with_the_ledger(self):
        self.raise_("b-1", NOW - DAY)
        beads = [bead("b-1", "Bills", "blocked")]
        before = self.snap(beads).version
        assert self.snap(beads).version == before
        self.verbs.cause(BeadId("b-1"), "b-1-1", "environment")
        assert self.snap(beads).version != before


class Decisions(Case):
    def test_adr_rows_carry_reuse_last_use_and_the_prune_offer(self):
        adrs = self.stores.adrs(REPO)
        old = adrs.add(Adr(id="", n=0, repo=REPO, text="old", question="q", answer="a", ask="x-1", bead="x", key="k", t=NOW - 40 * DAY))
        used = adrs.add(Adr(id="", n=0, repo=REPO, text="used", question="q", answer="a", ask="x-2", bead="x", key="k", t=NOW - 40 * DAY))
        fresh = adrs.add(Adr(id="", n=0, repo=REPO, text="fresh", question="q", answer="a", ask="x-3", bead="x", key="k", t=NOW - DAY))
        adrs.use(used.id, "b-1", "r1", NOW - 3 * DAY)
        adrs.use(used.id, "b-2", "r2", NOW - DAY)
        reuses = adrs.reuses()
        adrs.put(fresh.replace(retired_t=NOW, retired_by="denis"))
        ins = [AdrIn(a, reuses.get(a.id, (0, 0.0))[0], reuses.get(a.id, (0, 0.0))[1] or None) for a in adrs.in_force()]
        rows = {r.id: r for r in self.snap([], adrs=ins).adrs}
        assert fresh.id not in rows  # retired: no longer in force
        assert (
            [(i, rows[i].reuses, rows[i].last_used, rows[i].prune, rows[i].project) for i in (old.id, used.id)]
            == [(old.id, 0, None, True, loop_key(REPO)), (used.id, 2, NOW - DAY, False, loop_key(REPO))]
        )


class Learning(Case):
    def test_weekly_series_from_the_ledger_and_the_landed_runs(self):
        self.raise_("b-0", NOW - 20 * DAY)  # never answered: counts as raised, not as durable
        last = self.raise_("b-1", NOW - 10 * DAY, cause="requirement")
        self.verbs.answer(BeadId("b-1"), "text", "x")
        self.verbs.stick(last.id, Stick.FIX, "clarified")
        self.raise_("b-2", NOW - 3600, cause="requirement")
        landings = [Landing(NOW - 10 * DAY + 60, 2), Landing(NOW - 10 * DAY + 90, 0), Landing(NOW - 3600, 1)]
        got = self.snap([bead("b-2", "x")], landings=landings).learning
        assert len(got.weeks) == 4  # from the week of the oldest row, not eight padded with zeros
        for series in (got.asks_per_landed, got.repeat_asks, got.sendbacks_per_bead, got.durable_pct):
            assert len(series) == len(got.weeks)
        assert (got.asks_per_landed[-1], got.sendbacks_per_bead[-1], got.durable_pct[-1]) == (1.0, 1.0, 0.0)
        k = got.durable_pct.index(100.0)  # the week of the answered ask: 1 ask, 2 landed
        assert (got.asks_per_landed[k], got.sendbacks_per_bead[k]) == (0.5, 1.0)
        assert [(c.cause, c.now, c.prev) for c in got.causes] == [(OwnerCause.REQUIREMENT, 1, 1)]  # this week and last, asks only

    def test_nothing_recorded_is_an_empty_series_not_eight_zeros(self):
        got = self.snap([]).learning
        assert (got.weeks, got.asks_per_landed, got.causes) == ([], [], [])

    def test_a_repeat_counts_in_its_week(self):
        first = self.raise_("b-0", NOW - 9 * DAY)
        self.verbs.answer(BeadId("b-0"), "text", "x")
        again = self.raise_("b-1", NOW - 3600)
        assert again.similar == [SimilarRef(kind="ask", id=first.id)]
        got = self.snap([bead("b-1", "x")]).learning
        assert got.repeat_asks[-1] == 1
        assert sum(got.repeat_asks) == 1


class Stick_(Case):
    """POST /api/stick: the dashboard's write through Ports into the Intake verb."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeBeads()
        self.fake.beads[BeadId("b-1")] = Bead(id=BeadId("b-1"), title="Bills", status="blocked", description="Pay the bills.")
        self.factory = FakeBeads(prefix="tl")
        self.dash = make_dash(answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW, factory=lambda: self.factory),
                              config=self.tmp.name, clock=lambda: NOW)
        repo = Path(self.tmp.name) / "demo"
        repo.mkdir()
        write_repos(self.dash.env.config.repos(), repo)
        self.repo = repo
        self.asks = AskStore.at(self.dash.env.config)
        self.ask = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("b-1"), run="r", brief_hash="h", repo=str(repo), title="Bills", now=NOW - 60))[0])
        self.post("answer", {"project": loop_key(self.repo), "ask": self.ask.id, "kind": "answer", "option": 0})

    def post(self, verb, body):
        code, out = self.dash.writes.post(verb, body)
        assert code == 200
        return wire.load(Result, out)

    def stick(self, outcome, text=""):
        return self.post("stick", {"project": loop_key(self.repo), "ask": self.ask.id, "outcome": outcome, "text": text})

    def adrs(self):
        return AdrStore.at(self.dash.env.config, str(self.repo))

    def adr_beads(self):
        return [b for b in self.fake.beads.values() if "adr" in b.labels]

    def plant(self, retired=False):
        """The ADR as the cache holds it once its file is on the base commit."""
        return self.adrs().add(Adr(id="", n=0, repo=str(self.repo), text="Rent is weekly.", question="q", answer="a", ask="x-1",
                                   bead="x", key="k", t=NOW, retired_t=NOW if retired else None, retired_by="denis" if retired else ""))

    def test_adr_files_a_bead_for_the_lane_to_land_the_file(self):
        assert self.stick("adr", "Rent is weekly.") == Result(ok=True)
        [made] = self.adr_beads()
        assert (made.title, f"- Ask: {self.ask.id}\n" in made.description) == ("ADR: Rent is weekly.", True)
        assert not Path(self.tmp.name, "decisions").exists()  # tl writes no ADR of its own
        rows = self.asks.history(self.ask.id)
        assert (rows[-1].event, rows[-1].outcome, rows[-1].outcome_ref) == ("stick", Stick.ADR, made.id)

    def test_factory_fix_and_the_record_only_outcomes(self):
        assert self.stick("factory", "prompt: ask which bills") == Result(ok=True)
        assert [b.title for b in self.factory.beads.values()] == ["prompt: ask which bills"]
        assert self.stick("fix", "Rent is weekly.") == Result(ok=True)
        assert "Rent is weekly." in self.fake.beads[BeadId("b-1")].description
        assert self.stick("demote") == Result(ok=True)
        assert self.asks.history(self.ask.id)[-1].event == "demote"
        assert self.stick("once") == Result(ok=True)
        assert self.asks.history(self.ask.id)[-1].outcome == Stick.ONCE

    def test_ref_needs_a_decision_and_a_refusal_changes_nothing(self):
        res = self.stick("ref", "ADR-4")
        assert (res.ok, "not a decision" in res.message) == (False, True)
        assert self.stick("fix").ok is False
        assert self.asks.history(self.ask.id)[-1].event == "answer"
        assert self.post("stick", {"project": "nowhere", "ask": self.ask.id, "outcome": "adr"}).ok is False

    def test_a_stick_leaves_the_cache_to_the_files_and_a_write_drops_the_cached_read(self):
        worlds = self.dash.reads.worlds
        assert worlds.adrs(str(self.repo)) == []
        self.stick("adr", "Rent is weekly.")
        assert worlds.adrs(str(self.repo)) == []  # pending until its file is on the base commit
        self.plant()
        self.post("prune", {"project": loop_key(self.repo), "adr": "ADR-1"})  # a write that succeeds drops the cached read
        assert [a.adr.id for a in worlds.adrs(str(self.repo))] == ["ADR-1"]

    def test_prune_files_a_retire_bead_once_and_leaves_the_cache_to_the_file(self):
        self.plant()
        assert self.post("prune", {"project": loop_key(self.repo), "adr": "ADR-1"}) == Result(ok=True)
        assert self.post("prune", {"project": loop_key(self.repo), "adr": "ADR-1"}) == Result(ok=True)
        assert [b.title for b in self.adr_beads()] == ["Retire ADR-1"]
        assert must(self.adrs().get("ADR-1")).retired_t is None
        assert "not a decision" in self.post("prune", {"project": loop_key(self.repo), "adr": "ADR-9"}).message
        assert not self.post("prune", {"project": "nowhere", "adr": "ADR-1"}).ok

    def test_a_retired_decision_cannot_be_pruned_again_or_linked(self):
        self.plant(retired=True)
        again = self.post("prune", {"project": loop_key(self.repo), "adr": "ADR-1"})
        assert (again.ok, "already retired" in again.message) == (False, True)
        assert self.stick("ref", "ADR-1").ok is False

    def test_an_unanswered_ask_cannot_stick(self):
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), raiser.Asking(
            bead=BeadId("b-2"), run="r", brief_hash="h", repo=self.tmp.name, title="x", now=NOW))[0])
        res = self.post("stick", {"project": loop_key(self.repo), "ask": other.id, "outcome": "adr"})
        assert (res.ok, res.message) == (False, "answer the ask first")
        assert self.dash.writes.post("stick", {"project": loop_key(self.repo), "ask": "x", "outcome": "maybe"})[0] == 400
