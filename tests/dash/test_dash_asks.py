"""The ask records the page shows: the AskCard fields, the soft ask's marker, the ledger rows, the decisions in
force, the learning series, and POST /api/stick through Ports."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from asks.dash_ports import answering
from support.dashes import make_dash
from support.dashlogs import T, bead
from support.fake_beads import FakeBeads
from support.narrow import must

from taskloop.app.asks import intake, raiser
from taskloop.contracts import wire
from taskloop.contracts.ask import SimilarRef, ThreadEntry
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Column, Marker, OwnerCause, Result, Stick
from taskloop.contracts.ledger import Adr
from taskloop.contracts.stores import AskStore
from taskloop.domain.asks import specs
from taskloop.stores.memory import fake_stores
from taskloop_dash.views import bead_detail, snapshot
from taskloop_dash.views.board import Board
from taskloop_dash.views.world import AdrIn, Landing, ProjectIn, World

DAY = 86400.0
NOW = T + 20 * DAY
REPO = "/r/lifesim"
Q = "Which bills are weekly?"
OPTS = [{"label": "Rent weekly", "cost": "none", "answer": "rent weekly", "recommended": True},
        {"label": "All weekly", "cost": "a run", "answer": "all weekly", "recommended": False}]


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Case(unittest.TestCase):
    def setUp(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(self.restore_tz)
        self.stores = fake_stores()
        self.asks = self.stores.asks
        self.beads = FakeBeads()
        for k in range(5):
            self.beads.beads[f"b-{k}"] = Bead(id=f"b-{k}", title="x", status="blocked")
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
        p = ProjectIn(id="lifesim", name="lifesim", beads=beads, adrs=list(adrs))
        live = live if live is not None else {a.bead: a for a in self.asks.live()}
        return World(now=NOW, host="box", version="v1", projects=[p], runs={}, asks=live, ledger=self.asks.rows(), landings=list(landings))

    def snap(self, beads, **kw):
        return snapshot.build(self.world(beads, **kw))


class Cards(Case):
    def test_an_ask_card_carries_the_typed_fields_of_the_ask(self):
        key = self.raise_("b-0", T).key
        adr = self.stores.adrs(REPO).add(Adr(id="", n=0, repo=REPO, text="Rent is weekly", question=Q, answer="rent", ask="b-0-1",
                                             bead="b-0", key=key, t=NOW - 5 * DAY))
        a = self.raise_("b-1", NOW - DAY, cause="requirement", adrs=self.stores.adrs(REPO))
        self.assertEqual(a.similar, [SimilarRef(kind="adr", id=adr.id)])
        self.asks.put(a.replace(thread=[ThreadEntry(by="owner", t=NOW - 100, md="why?"),
                                                     ThreadEntry(by="helper", t=NOW - 90, md="because")]))
        beads = [bead("b-1", "Bills"), bead("b-2", "Done after", "closed", closed_at=iso(NOW - 3600)),
                 bead("b-3", "Done before", "closed", closed_at=iso(NOW - 5 * DAY))]
        asks = {x.bead: x for x in self.snap(beads, adrs=[AdrIn(adr, 2, NOW - 100)]).asks}
        card = asks["b-1"]
        self.assertEqual((card.blocking, card.owner_cause, card.cause_by, card.default), (True, OwnerCause.REQUIREMENT, "agent", ""))
        self.assertEqual([(m.by, m.md) for m in card.thread], [("owner", "why?"), ("helper", "because")])
        self.assertEqual((card.ask_backs, card.stale), (1, 1))
        self.assertEqual(must(card.similar).answer, "Rent is weekly")
        self.assertEqual((must(card.similar).bead, must(card.similar).t), ("b-0", NOW - 5 * DAY))

    def test_a_card_matches_a_past_answered_ask_when_no_decision_is_in_force(self):
        first = self.raise_("b-0", NOW - 9 * DAY)
        self.verbs.answer("b-0", "text", "rent weekly")
        a = self.raise_("b-1", NOW - DAY)
        self.assertEqual(a.similar, [SimilarRef(kind="ask", id=first.id)])
        card = self.snap([bead("b-1", "Bills")]).asks[0]
        self.assertEqual((must(card.similar).bead, must(card.similar).answer, must(card.similar).question), ("b-0", "rent weekly", Q))

    def test_the_owner_corrects_the_cause_and_the_card_shows_it(self):
        a = self.raise_("b-1", NOW - DAY, cause="process")
        self.assertEqual(self.verbs.cause("b-1", a.id, "environment"), "")
        card = self.snap([bead("b-1", "Bills")]).asks[0]
        self.assertEqual((card.owner_cause, card.cause_by), (OwnerCause.ENVIRONMENT, "owner"))

    def test_a_soft_ask_marks_the_bead_without_moving_its_column_and_the_drawer_shows_it(self):
        a = self.raise_("b-1", NOW - DAY, default="went on with weekly rent")
        beads = [bead("b-1", "Bills", "in_progress", assignee="tl-a")]
        w = self.world(beads)
        s = snapshot.build(w)
        card = s.beads[0]
        self.assertEqual((card.marker, card.column, card.tone), (Marker.SOFT_ASK, Column.WORKING, "you"))
        self.assertIn(a.decision, card.status)
        ask = s.asks[0]
        self.assertEqual((ask.blocking, ask.default), (False, "went on with weekly rent"))
        detail = bead_detail.build(Board(w), w.projects[0], beads[0], [], [])
        self.assertEqual(must(detail.ask).id, a.id)

    def test_a_blocking_ask_still_fills_the_questions_column(self):
        self.raise_("b-1", NOW - DAY)
        card = self.snap([bead("b-1", "Bills", "blocked")]).beads[0]
        self.assertEqual((card.marker, card.column), (Marker.ASK, Column.QUESTIONS))


class Ledger(Case):
    def test_rows_hold_open_soft_and_answered_asks_newest_first_with_cause_and_outcome(self):
        done = self.raise_("b-1", NOW - 6 * DAY, cause="requirement")
        self.verbs.answer("b-1", "text", "rent weekly")
        self.verbs.cause("b-1", done.id, "decision")
        self.asks.consume("b-1", NOW - 5 * DAY)
        self.asks.stuck("b-1", done.id, Stick.ONCE, "", NOW - 5 * DAY)
        hard = self.raise_("b-2", NOW - 2 * DAY)
        soft = self.raise_("b-3", NOW - DAY, default="weekly")
        gone = self.raise_("b-4", NOW - 3 * DAY)
        self.asks.withdraw("b-4", gone.id, "n/a", NOW)
        rows = self.snap([bead(b, b) for b in ("b-2", "b-3", "b-4")]).ledger
        self.assertEqual([(r.ask, r.status) for r in rows], [(soft.id, "open_soft"), (hard.id, "open"), (done.id, "answered")])
        old = rows[2]
        self.assertEqual((old.answer, old.outcome, old.cause, old.project, old.question, old.t),
                         ("rent weekly", Stick.ONCE, OwnerCause.DECISION, "lifesim", Q, NOW - 6 * DAY))
        self.assertEqual((rows[0].outcome, rows[0].cause), (None, OwnerCause.DECISION))

    def test_an_open_row_of_a_bead_the_snapshot_does_not_show_is_left_out_but_an_answered_one_stays(self):
        self.raise_("b-1", NOW - 6 * DAY)
        self.verbs.answer("b-1", "text", "x")
        self.raise_("b-2", NOW - DAY)
        self.assertEqual([r.status for r in self.snap([bead("b-1", "x", "closed", closed_at=iso(NOW - 4 * DAY))]).ledger], ["answered"])

    def test_the_snapshot_version_moves_with_the_ledger(self):
        self.raise_("b-1", NOW - DAY)
        beads = [bead("b-1", "Bills", "blocked")]
        before = self.snap(beads).version
        self.assertEqual(self.snap(beads).version, before)
        self.verbs.cause("b-1", "b-1-1", "environment")
        self.assertNotEqual(self.snap(beads).version, before)


class Decisions(Case):
    def test_adr_rows_carry_reuse_last_use_and_the_prune_offer(self):
        adrs = self.stores.adrs(REPO)
        old = adrs.add(Adr(id="", n=0, repo=REPO, text="old", question="q", answer="a", ask="x-1", bead="x", key="k", t=NOW - 40 * DAY))
        used = adrs.add(Adr(id="", n=0, repo=REPO, text="used", question="q", answer="a", ask="x-2", bead="x", key="k", t=NOW - 40 * DAY))
        fresh = adrs.add(Adr(id="", n=0, repo=REPO, text="fresh", question="q", answer="a", ask="x-3", bead="x", key="k", t=NOW - DAY))
        adrs.use(used.id, "b-1", "r1", NOW - 3 * DAY)
        adrs.use(used.id, "b-2", "r2", NOW - DAY)
        reuses = adrs.reuses()
        ins = [AdrIn(a, reuses.get(a.id, (0, 0.0))[0], reuses.get(a.id, (0, 0.0))[1] or None) for a in adrs.all()]
        self.assertEqual(adrs.retire(fresh.id, "denis", NOW), "")
        ins = [AdrIn(a, reuses.get(a.id, (0, 0.0))[0], reuses.get(a.id, (0, 0.0))[1] or None) for a in adrs.in_force()]
        rows = {r.id: r for r in self.snap([], adrs=ins).adrs}
        self.assertNotIn(fresh.id, rows)  # retired: no longer in force
        self.assertEqual([(i, rows[i].reuses, rows[i].last_used, rows[i].prune, rows[i].project) for i in (old.id, used.id)],
                         [(old.id, 0, None, True, "lifesim"), (used.id, 2, NOW - DAY, False, "lifesim")])


class Learning(Case):
    def test_weekly_series_from_the_ledger_and_the_landed_runs(self):
        self.raise_("b-0", NOW - 20 * DAY)  # never answered: counts as raised, not as durable
        last = self.raise_("b-1", NOW - 10 * DAY, cause="requirement")
        self.verbs.answer("b-1", "text", "x")
        self.verbs.stick(last.id, Stick.FIX, "clarified")
        self.raise_("b-2", NOW - 3600, cause="requirement")
        landings = [Landing(NOW - 10 * DAY + 60, 2), Landing(NOW - 10 * DAY + 90, 0), Landing(NOW - 3600, 1)]
        got = self.snap([bead("b-2", "x")], landings=landings).learning
        self.assertEqual(len(got.weeks), 4)  # from the week of the oldest row, not eight padded with zeros
        for series in (got.asks_per_landed, got.repeat_asks, got.sendbacks_per_bead, got.durable_pct):
            self.assertEqual(len(series), len(got.weeks))
        self.assertEqual((got.asks_per_landed[-1], got.sendbacks_per_bead[-1], got.durable_pct[-1]), (1.0, 1.0, 0.0))
        k = got.durable_pct.index(100.0)  # the week of the answered ask: 1 ask, 2 landed
        self.assertEqual((got.asks_per_landed[k], got.sendbacks_per_bead[k]), (0.5, 1.0))
        self.assertEqual([(c.cause, c.now, c.prev) for c in got.causes], [(OwnerCause.REQUIREMENT, 1, 1)])  # this week and last, asks only

    def test_nothing_recorded_is_an_empty_series_not_eight_zeros(self):
        got = self.snap([]).learning
        self.assertEqual((got.weeks, got.asks_per_landed, got.causes), ([], [], []))

    def test_a_repeat_counts_in_its_week(self):
        first = self.raise_("b-0", NOW - 9 * DAY)
        self.verbs.answer("b-0", "text", "x")
        again = self.raise_("b-1", NOW - 3600)
        self.assertEqual(again.similar, [SimilarRef(kind="ask", id=first.id)])
        got = self.snap([bead("b-1", "x")]).learning
        self.assertEqual(got.repeat_asks[-1], 1)
        self.assertEqual(sum(got.repeat_asks), 1)


class Stick_(unittest.TestCase):
    """POST /api/stick: the dashboard's write through Ports into the Intake verb."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeBeads()
        self.fake.beads["b-1"] = Bead(id="b-1", title="Bills", status="blocked", description="Pay the bills.")
        self.factory = FakeBeads(prefix="tl")
        self.dash = make_dash(answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW, factory=lambda: self.factory),
                              config=self.tmp.name, clock=lambda: NOW)
        repo = Path(self.tmp.name) / "demo"
        repo.mkdir()
        self.dash.env.config.repos().write_text(json.dumps({str(repo): {}}))
        self.asks = AskStore.at(self.dash.env.config)
        self.ask = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead="b-1", run="r", brief_hash="h", repo=str(repo), title="Bills", now=NOW - 60))[0])
        self.post("answer", {"project": "demo", "ask": self.ask.id, "kind": "answer", "option": 0})

    def post(self, verb, body):
        code, out = self.dash.writes.post(verb, body)
        self.assertEqual(code, 200)
        return wire.load(Result, out)

    def stick(self, outcome, text=""):
        return self.post("stick", {"project": "demo", "ask": self.ask.id, "outcome": outcome, "text": text})

    def test_adr_is_written_under_the_state_dir_and_the_planner_store_reads_it(self):
        self.assertEqual(self.stick("adr", "Rent is weekly."), Result(ok=True))
        found = list(Path(self.tmp.name, "decisions").glob("*/ADR-1.json"))
        self.assertEqual(len(found), 1)
        self.assertEqual(json.loads(found[0].read_text())["text"], "Rent is weekly.")
        rows = self.asks.history(self.ask.id)
        self.assertEqual((rows[-1].event, rows[-1].outcome, rows[-1].outcome_ref), ("stick", Stick.ADR, "ADR-1"))

    def test_factory_fix_and_the_record_only_outcomes(self):
        self.assertEqual(self.stick("factory", "prompt: ask which bills"), Result(ok=True))
        self.assertEqual([b.title for b in self.factory.beads.values()], ["prompt: ask which bills"])
        self.assertEqual(self.stick("fix", "Rent is weekly."), Result(ok=True))
        self.assertIn("Rent is weekly.", self.fake.beads["b-1"].description)
        self.assertEqual(self.stick("demote"), Result(ok=True))
        self.assertEqual(self.asks.history(self.ask.id)[-1].event, "demote")
        self.assertEqual(self.stick("once"), Result(ok=True))
        self.assertEqual(self.asks.history(self.ask.id)[-1].outcome, Stick.ONCE)

    def test_ref_needs_a_decision_and_a_refusal_changes_nothing(self):
        res = self.stick("ref", "ADR-4")
        self.assertEqual((res.ok, "not a decision" in res.message), (False, True))
        self.assertEqual(self.stick("fix").ok, False)
        self.assertEqual(self.asks.history(self.ask.id)[-1].event, "answer")
        self.assertEqual(self.post("stick", {"project": "nowhere", "ask": self.ask.id, "outcome": "adr"}).ok, False)

    def test_prune_retires_a_decision_and_keeps_it_in_the_store(self):
        self.stick("adr", "Rent is weekly.")
        res = self.post("prune", {"project": "demo", "adr": "ADR-1"})
        self.assertEqual(res, Result(ok=True))
        [path] = Path(self.tmp.name, "decisions").glob("*/ADR-1.json")
        got = json.loads(path.read_text())
        self.assertEqual((got["retired_by"], got["retired_t"], got["text"]), ("dash", NOW, "Rent is weekly."))
        again = self.post("prune", {"project": "demo", "adr": "ADR-1"})
        self.assertEqual((again.ok, "already retired" in again.message), (False, True))
        self.assertIn("not a decision", self.post("prune", {"project": "demo", "adr": "ADR-9"}).message)
        self.assertFalse(self.post("prune", {"project": "nowhere", "adr": "ADR-1"}).ok)
        self.assertEqual(self.stick("ref", "ADR-1").ok, False)  # a retired decision cannot be linked

    def test_an_unanswered_ask_cannot_stick(self):
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), raiser.Asking(
            bead="b-2", run="r", brief_hash="h", repo=self.tmp.name, title="x", now=NOW))[0])
        res = self.post("stick", {"project": "demo", "ask": other.id, "outcome": "adr"})
        self.assertEqual((res.ok, res.message), (False, "answer the ask first"))
        self.assertEqual(self.dash.writes.post("stick", {"project": "demo", "ask": "x", "outcome": "maybe"})[0], 400)


if __name__ == "__main__":
    unittest.main()
