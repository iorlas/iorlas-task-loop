"""Make it stick: each outcome of an answered ask through the Intake verb, its effect and its ledger row."""
from unittest import mock

import pytest
from support.fake_beads import FakeBeads
from support.memstores import fake_stores
from support.tiers import domain

from tlasks import intake, raiser
from tlasks import similar
from tlkernel import askspecs as specs
from tlkernel.ask import SimilarRef
from tlkernel.bead import Bead
from tlkernel.dash import Stick
from tlkernel.ids import BeadId
from tlkernel.ledger import Adr
from tltestkit.case import Case
from tltestkit.narrow import must

T = 1000.0
Q = "Which save format should the engine keep for old files?"
OPTS = [{"label": "Keep v1", "cost": "none", "answer": "keep v1", "recommended": True},
        {"label": "Migrate", "cost": "a run", "answer": "migrate", "recommended": False}]
REPO = "/r/demo"


@domain
class Stick_(Case):
    def setup_method(self) -> None:
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

    def adr_beads(self):
        return [b for b in self.beads.beads.values() if "adr" in b.labels]

    def test_adr_files_a_bead_that_lands_the_decision_and_marks_the_ask(self) -> None:
        assert self.verbs.stick(self.ask.id, Stick.ADR, "Saves stay v1 until a bead says otherwise.") == ""
        [made] = self.adr_beads()
        assert made.title == "ADR: Saves stay v1 until a bead says otherwise."
        for want in (f"- Ask: {self.ask.id}\n", "- Bead: t-1\n", f"- Key: {self.ask.key}\n", "- By: denis\n", "docs/adr/NNNN-",
                     self.ask.decision, "keep v1", "Saves stay v1 until a bead says otherwise."):
            assert want in made.description, want
        assert (self.last().event, self.last().outcome, self.last().outcome_ref) == ("stick", Stick.ADR, made.id)
        got = must(self.asks.get(BeadId("t-1")))
        assert (got.outcome, got.outcome_ref) == (Stick.ADR, made.id)
        assert any(c.text.startswith("Owner (tl) stick") for c in self.beads.comments(BeadId("t-1")))
        assert self.stores.adrs(REPO).all() == []  # the cache fills when the file is on the base commit, not before

    def test_adr_without_words_drafts_one_from_the_question_and_the_answer_and_is_filed_once(self) -> None:
        self.verbs.stick(self.ask.id, Stick.ADR)
        self.verbs.stick(self.ask.id, Stick.ADR)
        [made] = self.adr_beads()
        assert f"{self.ask.decision} Decided: keep v1" in made.description
        assert len([r for r in self.asks.history(self.ask.id) if r.event == "stick"]) == 1

    def test_an_ask_whose_decision_has_landed_is_linked_to_it_and_no_second_bead_is_filed(self) -> None:
        landed = self.stores.adrs(REPO).add(Adr(id="", n=0, repo=REPO, text="v1", question=Q, answer="v1", ask=self.ask.id, bead="t-1",
                                                key="k", t=T))
        assert self.verbs.stick(self.ask.id, Stick.ADR, "again") == ""
        assert (self.adr_beads(), self.last().outcome_ref) == ([], landed.id)

    def test_factory_files_a_bead_in_the_task_loop_repo_and_the_current_bead_does_not_wait(self) -> None:
        assert self.verbs.stick(self.ask.id, Stick.FACTORY, "bead template: say which save format") == ""
        [made] = self.factory.beads.values()
        assert (made.title, made.labels) == ("bead template: say which save format", ["factory"])
        assert self.ask.id in made.description
        assert self.last().outcome_ref == made.id
        assert self.beads.beads[BeadId("t-1")].status == "open"  # the answer opened it; the factory bead is no blocker
        assert self.beads.beads[BeadId("t-1")].dependencies == []

    def test_factory_with_no_task_loop_repo_changes_nothing(self) -> None:
        verbs = intake.Intake(self.asks, self.beads, lambda: T + 5, "denis", self.stores.adrs, lambda: None)
        assert "no task-loop repo" in verbs.stick(self.ask.id, Stick.FACTORY, "x")
        assert (self.last().event, must(self.asks.get(BeadId("t-1"))).outcome) == ("answer", None)

    def test_fix_appends_the_owners_words_to_the_bead_text(self) -> None:
        assert "say what" in self.verbs.stick(self.ask.id, Stick.FIX)
        assert self.verbs.stick(self.ask.id, Stick.FIX, "Saves stay in format v1.") == ""
        text = self.beads.beads[BeadId("t-1")].description
        assert text.startswith("Keep saves working.\n\nClarified by the owner")
        assert text.endswith("Saves stay in format v1.")
        assert (self.last().outcome, self.last().outcome_ref) == (Stick.FIX, "t-1")

    def test_ref_links_the_ask_to_a_decision_named_or_matched(self) -> None:
        adrs = self.stores.adrs(REPO)
        made = adrs.add(Adr(id="", n=0, repo=REPO, text="v1", question=Q, answer="v1", ask="x-1", bead="x", key="k", t=T))
        assert "ADR-n" in self.verbs.stick(self.ask.id, Stick.REF)  # nothing matched, nothing named
        assert "ADR-9 is not a decision" in self.verbs.stick(self.ask.id, Stick.REF, "ADR-9")
        assert self.verbs.stick(self.ask.id, Stick.REF, made.id) == ""
        assert self.last().outcome_ref == made.id

    def test_ref_defaults_to_the_decision_the_ask_matched(self) -> None:
        adrs = self.stores.adrs(REPO)
        key = similar.key_of(self.ask.ask_class, self.ask.decision)
        made = adrs.add(Adr(id="", n=0, repo=REPO, text="v1", question=Q, answer="v1", ask="x-1", bead="x", key=key, t=T))
        second = must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-2"), run="r", brief_hash="h", repo=REPO, title="x", now=T + 30), adrs)[0])
        assert second.similar == [SimilarRef(kind="adr", id=made.id), SimilarRef(kind="ask", id=self.ask.id)]  # the decision first
        self.beads.beads[BeadId("t-2")] = Bead(id=BeadId("t-2"), title="x", status="blocked")
        self.verbs.answer(BeadId("t-2"), "text", "v1")
        assert self.verbs.stick(second.id, Stick.REF) == ""
        assert self.asks.history(second.id)[-1].outcome_ref == made.id

    def test_demote_and_once_record_the_outcome_only(self) -> None:
        for outcome, event in ((Stick.DEMOTE, "demote"), (Stick.ONCE, "stick")):
            assert self.verbs.stick(self.ask.id, outcome) == ""
            assert (self.last().event, self.last().outcome) == (event, outcome)
        assert (self.stores.adrs(REPO).all(), list(self.factory.beads)) == ([], [])

    def test_an_unanswered_or_unknown_ask_is_refused(self) -> None:
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), raiser.Asking(
            bead=BeadId("t-2"), run="r", brief_hash="h", repo=REPO, title="x", now=T))[0])
        assert self.verbs.stick(other.id, Stick.ADR) == "answer the ask first"
        assert self.verbs.stick("nope-1", Stick.ADR) == "this ask is not in the ledger"
        assert self.stores.adrs(REPO).all() == []

    def test_it_holds_for_an_ask_a_newer_ask_replaced(self) -> None:
        self.asks.consume(BeadId("t-1"), T + 6)
        must(raiser.raise_ask(self.asks, specs.open_question(Q, OPTS), raiser.Asking(
            bead=BeadId("t-1"), run="r2", brief_hash="h2", repo=REPO, title="Saves", now=T + 40))[0])
        assert self.verbs.stick(self.ask.id, Stick.ADR, "still v1") == ""
        assert must(self.asks.get(BeadId("t-1"))).outcome is None  # the newer ask is untouched
        [made] = self.adr_beads()
        assert f"- Ask: {self.ask.id}\n" in made.description

    def stick_with_one_ledger_failure(self, outcome: Stick) -> None:
        """The first ledger write of the outcome fails after its effect was made; the owner taps again."""
        real, calls = self.asks.stuck, []

        def flaky(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise OSError("disk")
            return real(*args, **kwargs)

        with mock.patch.object(self.asks, "stuck", flaky):
            with pytest.raises(OSError, match="disk"):
                self.verbs.stick(self.ask.id, outcome, "Saves stay v1.")
            assert self.verbs.stick(self.ask.id, outcome, "Saves stay v1.") == ""

    def test_an_adr_stick_retried_after_the_ledger_write_failed_files_one_bead(self) -> None:
        self.stick_with_one_ledger_failure(Stick.ADR)
        assert len(self.adr_beads()) == 1

    def test_a_factory_stick_retried_after_the_ledger_write_failed_files_one_bead(self) -> None:
        self.stick_with_one_ledger_failure(Stick.FACTORY)
        assert len(self.factory.beads) == 1
