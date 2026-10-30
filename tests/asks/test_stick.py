"""Make it stick: each outcome of an answered ask through the Intake verb, its effect and its ledger row."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.narrow import must
from support.tiers import domain

from taskloop.app.asks import intake, raiser
from taskloop.contracts.ask import SimilarRef
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Stick
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ledger import Adr
from taskloop.domain.asks import similar, specs
from taskloop.stores.memory import fake_stores

T = 1000.0
Q = "Which save format should the engine keep for old files?"
OPTS = [{"label": "Keep v1", "cost": "none", "answer": "keep v1", "recommended": True},
        {"label": "Migrate", "cost": "a run", "answer": "migrate", "recommended": False}]
REPO = "/r/demo"


@domain
class Stick_(unittest.TestCase):
    def setUp(self) -> None:
        self.stores = fake_stores()
        self.asks = self.stores.asks
        self.beads = FakeBeads()
        self.beads.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="Saves", status="blocked", description="Keep saves working.")
        self.factory = FakeBeads(prefix="tl")
        self.verbs = intake.Intake(self.asks, self.beads, lambda: T + 5, "denis", self.stores.adrs, lambda: self.factory)
        self.ask = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-1"), run="r", brief_hash="h", repo=REPO, title="Saves", now=T))[0])
        self.verbs.answer(BeadId("t-1"), "text", "keep v1")

    def last(self):
        return self.asks.history(self.ask.id)[-1]

    def test_adr_files_a_decision_the_plan_stage_reads_and_marks_the_ask(self) -> None:
        self.assertEqual(self.verbs.stick(self.ask.id, Stick.ADR, "Saves stay v1 until a bead says otherwise."), "")
        [adr] = self.stores.adrs(REPO).all()
        self.assertEqual((adr.id, adr.text, adr.question, adr.answer, adr.ask, adr.bead, adr.by, adr.key),
                         ("ADR-1", "Saves stay v1 until a bead says otherwise.", self.ask.decision, "keep v1", self.ask.id, "t-1", "denis",
                          self.ask.key))
        self.assertEqual((self.last().event, self.last().outcome, self.last().outcome_ref), ("stick", Stick.ADR, "ADR-1"))
        got = must(self.asks.get("t-1"))
        self.assertEqual((got.outcome, got.outcome_ref), (Stick.ADR, "ADR-1"))
        self.assertTrue(any(c.text.startswith("Owner (tl) stick") for c in self.beads.comments(BeadId("t-1"))))

    def test_adr_without_words_drafts_one_from_the_question_and_the_answer_and_is_filed_once(self) -> None:
        self.verbs.stick(self.ask.id, Stick.ADR)
        self.verbs.stick(self.ask.id, Stick.ADR)
        [adr] = self.stores.adrs(REPO).all()
        self.assertEqual(adr.text, f"{self.ask.decision} Decided: keep v1")
        self.assertEqual(len([r for r in self.asks.history(self.ask.id) if r.event == "stick"]), 1)

    def test_an_adr_of_a_later_ask_is_numbered_on(self) -> None:
        self.verbs.stick(self.ask.id, Stick.ADR, "one")
        again = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-1"), run="r", brief_hash="h", repo=REPO, title="Saves", now=T + 20))[0])
        self.verbs.answer(BeadId("t-1"), "text", "migrate")
        self.verbs.stick(again.id, Stick.ADR, "two")
        self.assertEqual([(a.id, a.text) for a in self.stores.adrs(REPO).all()], [("ADR-1", "one"), ("ADR-2", "two")])

    def test_factory_files_a_bead_in_the_task_loop_repo_and_the_current_bead_does_not_wait(self) -> None:
        self.assertEqual(self.verbs.stick(self.ask.id, Stick.FACTORY, "bead template: say which save format"), "")
        [made] = self.factory.beads.values()
        self.assertEqual((made.title, made.labels), ("bead template: say which save format", ["factory"]))
        self.assertIn(self.ask.id, made.description)
        self.assertEqual(self.last().outcome_ref, made.id)
        self.assertEqual(self.beads.beads[BeadId("t-1")].status, "open")  # the answer opened it; the factory bead is no blocker
        self.assertEqual(self.beads.beads[BeadId("t-1")].dependencies, [])

    def test_factory_with_no_task_loop_repo_changes_nothing(self) -> None:
        verbs = intake.Intake(self.asks, self.beads, lambda: T + 5, "denis", self.stores.adrs, lambda: None)
        self.assertIn("no task-loop repo", verbs.stick(self.ask.id, Stick.FACTORY, "x"))
        self.assertEqual((self.last().event, must(self.asks.get("t-1")).outcome), ("answer", None))

    def test_fix_appends_the_owners_words_to_the_bead_text(self) -> None:
        self.assertIn("say what", self.verbs.stick(self.ask.id, Stick.FIX))
        self.assertEqual(self.verbs.stick(self.ask.id, Stick.FIX, "Saves stay in format v1."), "")
        text = self.beads.beads[BeadId("t-1")].description
        self.assertTrue(text.startswith("Keep saves working.\n\nClarified by the owner"))
        self.assertTrue(text.endswith("Saves stay in format v1."))
        self.assertEqual((self.last().outcome, self.last().outcome_ref), (Stick.FIX, "t-1"))

    def test_ref_links_the_ask_to_a_decision_named_or_matched(self) -> None:
        adrs = self.stores.adrs(REPO)
        made = adrs.add(Adr(id="", n=0, repo=REPO, text="v1", question=Q, answer="v1", ask="x-1", bead="x", key="k", t=T))
        self.assertIn("ADR-n", self.verbs.stick(self.ask.id, Stick.REF))  # nothing matched, nothing named
        self.assertIn("ADR-9 is not a decision", self.verbs.stick(self.ask.id, Stick.REF, "ADR-9"))
        self.assertEqual(self.verbs.stick(self.ask.id, Stick.REF, made.id), "")
        self.assertEqual((must(adrs.get(made.id)).refs, self.last().outcome_ref), ([self.ask.id], made.id))

    def test_ref_defaults_to_the_decision_the_ask_matched(self) -> None:
        adrs = self.stores.adrs(REPO)
        key = similar.key_of(self.ask.ask_class, self.ask.decision)
        made = adrs.add(Adr(id="", n=0, repo=REPO, text="v1", question=Q, answer="v1", ask="x-1", bead="x", key=key, t=T))
        second = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-2"), run="r", brief_hash="h", repo=REPO, title="x", now=T + 30), adrs)[0])
        self.assertEqual(second.similar, [SimilarRef(kind="adr", id=made.id), SimilarRef(kind="ask", id=self.ask.id)])  # the decision first
        self.beads.beads[BeadId("t-2")] = Bead(id=BeadId("t-2"), title="x", status="blocked")
        self.verbs.answer(BeadId("t-2"), "text", "v1")
        self.assertEqual(self.verbs.stick(second.id, Stick.REF), "")
        self.assertEqual(must(adrs.get(made.id)).refs, [second.id])

    def test_demote_and_once_record_the_outcome_only(self) -> None:
        for outcome, event in ((Stick.DEMOTE, "demote"), (Stick.ONCE, "stick")):
            self.assertEqual(self.verbs.stick(self.ask.id, outcome), "")
            self.assertEqual((self.last().event, self.last().outcome), (event, outcome))
        self.assertEqual((self.stores.adrs(REPO).all(), list(self.factory.beads)), ([], []))

    def test_an_unanswered_or_unknown_ask_is_refused(self) -> None:
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), raiser.Asking(
            bead=BeadId("t-2"), run="r", brief_hash="h", repo=REPO, title="x", now=T))[0])
        self.assertEqual(self.verbs.stick(other.id, Stick.ADR), "answer the ask first")
        self.assertEqual(self.verbs.stick("nope-1", Stick.ADR), "this ask is not in the ledger")
        self.assertEqual(self.stores.adrs(REPO).all(), [])

    def test_it_holds_for_an_ask_a_newer_ask_replaced(self) -> None:
        self.asks.consume("t-1", T + 6)
        must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-1"), run="r2", brief_hash="h2", repo=REPO, title="Saves", now=T + 40))[0])
        self.assertEqual(self.verbs.stick(self.ask.id, Stick.ADR, "still v1"), "")
        self.assertEqual(must(self.asks.get("t-1")).outcome, None)  # the newer ask is untouched
        self.assertEqual(self.stores.adrs(REPO).all()[0].ask, self.ask.id)
