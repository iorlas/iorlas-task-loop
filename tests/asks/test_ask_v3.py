"""Ask v3: the new fields round-trip, an older ask file is absent, every transition leaves one ledger row, a repeat
matches a past ask and a decision in force, and a soft ask never makes a run wait."""
import json
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory, mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.askjson import unreadable_ask
from support.fake_beads import FakeBeads
from support.memstores import fake_stores
from support.narrow import must
from support.tiers import domain

from taskloop.app.asks import intake, raiser, sweeps
from taskloop.app.asks.paths import ask_marker
from taskloop.domain.asks import similar, specs
from tlkernel import wire
from tlkernel.ask import Ask, AskAnswer, SimilarRef, ThreadEntry
from tlkernel.askstore import AskStore
from tlkernel.bead import Bead
from tlkernel.dash import OwnerCause, Stick
from tlkernel.enums import AskStatus
from tlkernel.ids import BeadId
from tlkernel.ledger import Adr
from tlkernel.paths import ConfigDir

T = 1000.0
Q = "Which save format should the engine keep for old files?"
OPTS = [{"label": "Keep v1", "cost": "none", "answer": "keep v1", "recommended": True},
        {"label": "Migrate", "cost": "a run", "answer": "migrate", "recommended": False}]


def asking(bead: str = "t-1", now: float = T, repo: str = "/r/demo") -> raiser.Asking:
    return raiser.Asking(bead=BeadId(bead), run="r", brief_hash="h", repo=repo, title="T", now=now)


def question(cause: str = "decision", default: str = "") -> specs.AskSpec:
    return specs.open_question(Q, OPTS, cause, default)


@domain
class AskV3(Case):
    def setup_method(self) -> None:
        self.stores = fake_stores()
        self.asks = self.stores.asks

    def test_the_new_fields_round_trip_and_an_ask_is_version_3(self) -> None:
        ask = must(raiser.raise_ask(self.asks, question("requirement", "keep v1"), asking())[0]).replace(
            cause_by="owner", similar=[SimilarRef(kind="adr", id="ADR-2"), SimilarRef(kind="ask", id="t-0-1")],
            thread=[ThreadEntry(by="owner", t=T, md="why?")], outcome=Stick.ADR, outcome_ref="ADR-3")
        body = wire.dump(ask)
        assert body["v"] == 3
        assert wire.load(Ask, json.loads(json.dumps(body))) == ask
        assert (ask.owner_cause, ask.blocking, ask.default) == (OwnerCause.REQUIREMENT, False, "keep v1")

    def test_an_agent_declared_cause_outside_the_list_is_unknown(self) -> None:
        assert specs.declared("environment") == OwnerCause.ENVIRONMENT
        assert [specs.declared(x) for x in ("", None, "vibes")] == [OwnerCause.UNKNOWN] * 3
        a = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking())[0])
        assert (a.owner_cause, a.cause_by, a.blocking, a.default) == (OwnerCause.UNKNOWN, "agent", True, "")

    def test_an_ask_file_of_version_2_is_absent_and_listed_as_dropped(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            asks = AskStore.at(cfg)
            old = wire.dump(must(raiser.raise_ask(fake_stores().asks, question(), asking())[0])) | {"v": 2}
            unreadable_ask(cfg, "t-1", json.dumps(old))
            assert (asks.get(BeadId("t-1")), asks.orphans(), asks.live()) == (None, ["t-1"], [])


@domain
class Ledger(Case):
    def setup_method(self) -> None:
        self.asks = fake_stores().asks
        self.beads = FakeBeads()
        self.verbs = intake.Intake(self.asks, self.beads, lambda: T + 5, "denis")

    def rows(self, ask: str = "t-1-1") -> list[tuple[str, str, str]]:
        return [(r.event, r.answer, r.outcome.value if r.outcome else "") for r in self.asks.history(ask)]

    def test_each_transition_appends_one_row_carrying_cause_and_outcome(self) -> None:
        a = must(raiser.raise_ask(self.asks, question("process"), asking())[0])
        assert (a.id, self.rows()) == ("t-1-1", [("raise", "", "")])
        first = self.asks.history("t-1-1")[0]
        assert (first.question, first.cause, first.cause_by, first.t, first.repo) == (a.decision, OwnerCause.PROCESS, "agent", T, "/r/demo")
        self.beads.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="x", status="blocked")
        self.verbs.answer(BeadId("t-1"), "text", "keep v1")
        assert self.verbs.cause(BeadId("t-1"), "t-1-1", "requirement") == ""
        self.asks.consume(BeadId("t-1"), T + 9)
        assert self.asks.stuck(BeadId("t-1"), "t-1-1", Stick.DEMOTE, "", T + 9)
        assert [r[0] for r in self.rows()] == ["raise", "answer", "cause", "consume", "demote"]
        last = self.asks.history("t-1-1")[-1]
        assert (last.cause, last.cause_by, last.answer, last.outcome) == (OwnerCause.REQUIREMENT, "owner", "keep v1", Stick.DEMOTE)

    def test_withdraw_close_and_amend_leave_rows(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        self.asks.withdraw(BeadId("t-1"), "t-1-1", "no longer applies", T + 1)
        raiser.raise_ask(self.asks, question(), asking("t-2"))
        assert self.asks.close(BeadId("t-2"), "t-2-1", "the bead is closed", T + 2)
        raiser.raise_ask(self.asks, question(), asking("t-3"))
        self.asks.answer(BeadId("t-3"), "t-3-1", AskAnswer(action="text", text="a", t=T + 3, by="x"))
        self.asks.amend(BeadId("t-3"), "t-3-1", AskAnswer(action="text", text="b", t=T + 3, by="x"))
        assert [r[0] for r in self.rows("t-1-1")] == ["raise", "withdraw"]
        assert [r[0] for r in self.rows("t-2-1")] == ["raise", "close"]
        assert [r[:2] for r in self.rows("t-3-1")] == [("raise", ""), ("answer", "a"), ("answer", "b")]

    def test_the_ledger_outlives_the_ask_a_newer_ask_replaces(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        raiser.raise_ask(self.asks, question(), asking())
        assert must(self.asks.get(BeadId("t-1"))).id == "t-1-2"
        assert len(self.asks.history("t-1-1")) == 1
        assert len(self.asks.rows()) == 2

    def test_the_ledger_file_is_not_an_ask_and_no_sweep_removes_it(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            asks = AskStore.at(cfg)
            raiser.raise_ask(asks, question(), asking())
            assert (cfg.factory_db().is_file(), asks.orphans(), len(asks.rows())) == (True, [], 1)
            sweeps.close_stale(asks, lambda _r: FakeBeads(), ask_marker(cfg, "s"), T + 10 ** 7)
            assert len(asks.rows()) == 1


@domain
class Repeats(Case):
    def setup_method(self) -> None:
        self.stores = fake_stores()
        self.asks = self.stores.asks
        self.adrs = self.stores.adrs("/r/demo")

    def test_the_key_is_the_class_and_the_significant_words_of_the_question(self) -> None:
        cls = question().ask_class
        assert similar.key_of(cls, Q) == similar.key_of(cls, "Which save format should the engine KEEP for old files?!")
        assert similar.key_of(cls, Q) != similar.key_of(specs.missing_criteria().ask_class, Q)
        assert similar.key_of(cls, "the and for?") == ""

    def test_a_repeat_matches_a_past_answered_ask(self) -> None:
        first = must(raiser.raise_ask(self.asks, question(), asking("t-1"), self.adrs)[0])
        assert first.similar == []
        again = must(raiser.raise_ask(self.asks, question(), asking("t-2", T + 50), self.adrs)[0])
        assert again.similar == []  # the first was never answered: it teaches nothing
        intake.Intake(self.asks, FakeBeads(), lambda: T + 60, "denis").answer(BeadId("t-2"), "text", "keep v1")
        third = must(raiser.raise_ask(self.asks, question(), asking("t-3", T + 70), self.adrs)[0])
        assert third.similar == [SimilarRef(kind="ask", id="t-2-1")]
        assert self.asks.history("t-3-1")[0].similar == third.similar  # the ledger keeps what matched
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking("t-4"), self.adrs)[0])
        assert other.similar == []

    def test_a_repeat_matches_a_decision_in_force_first(self) -> None:
        key = similar.key_of(question().ask_class, question().decision)
        made = self.adrs.add(Adr(id="", n=0, repo="/r/demo", text="keep v1", question=Q, answer="keep v1", ask="x-1", bead="x", key=key,
                                 t=T))
        got = must(raiser.raise_ask(self.asks, question(), asking("t-9"), self.adrs)[0])
        assert got.similar == [SimilarRef(kind="adr", id=made.id)]
        elsewhere = must(raiser.raise_ask(self.asks, question(), asking("t-8"), self.stores.adrs("/r/other"))[0])
        assert elsewhere.similar == []  # another repo's decisions do not apply


@domain
class SoftAsks(Case):
    def setup_method(self) -> None:
        self.asks = fake_stores().asks

    def test_a_soft_ask_never_makes_the_run_wait_and_stays_open(self) -> None:
        a = must(raiser.raise_ask(self.asks, question("decision", "keep v1"), asking())[0])
        assert (a.blocking, a.default, a.status) == (False, "keep v1", AskStatus.OPEN)
        assert raiser.check(self.asks, BeadId("t-1"), "h", False, T + 1) == ("none", None)
        assert raiser.check(self.asks, BeadId("t-1"), "changed", True, T + 2) == ("none", None)  # a changed bead: not consumed
        assert must(self.asks.get(BeadId("t-1"))).consumed is None

    def test_a_soft_ask_is_not_parked_and_a_later_answer_is_used(self) -> None:
        raiser.raise_ask(self.asks, question("decision", "keep v1"), asking(repo="/nowhere"))
        marker = Path(mkdtemp()) / "no-marker-x"
        assert sweeps.park_stale(self.asks, lambda _r: FakeBeads(), marker, T + 10 ** 7, 0) == []
        intake.Intake(self.asks, FakeBeads(), lambda: T + 9, "denis").answer(BeadId("t-1"), "text", "migrate")
        state, got = raiser.check(self.asks, BeadId("t-1"), "h", False, T + 10)
        assert (state, must(must(got).answer).text) == ("answer", "migrate")

    def test_a_blocking_ask_still_waits(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        assert raiser.check(self.asks, BeadId("t-1"), "h", False, T + 1)[0] == "wait"
