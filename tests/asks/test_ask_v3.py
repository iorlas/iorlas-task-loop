"""Ask v3: the new fields round-trip, an older ask file is absent, every transition leaves one ledger row, a repeat
matches a past ask and a decision in force, and a soft ask never makes a run wait."""
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow import must
from support.tiers import domain

from taskloop.adapters.fake_beads import FakeBeads
from taskloop.app.asks import intake, raiser, sweeps
from taskloop.contracts import codec
from taskloop.contracts.ask import Ask, AskAnswer, SimilarRef, ThreadEntry
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import OwnerCause, Stick
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ledger import Adr
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore
from taskloop.domain.asks import similar, specs
from taskloop.stores.memory import fake_stores

T = 1000.0
Q = "Which save format should the engine keep for old files?"
OPTS = [{"label": "Keep v1", "cost": "none", "answer": "keep v1", "recommended": True},
        {"label": "Migrate", "cost": "a run", "answer": "migrate", "recommended": False}]


def asking(bead: str = "t-1", now: float = T, repo: str = "/r/demo") -> raiser.Asking:
    return raiser.Asking(bead=bead, run="r", brief_hash="h", repo=repo, title="T", now=now)


def question(cause: str = "decision", default: str = "") -> specs.AskSpec:
    return specs.open_question(Q, OPTS, cause, default)


@domain
class AskV3(unittest.TestCase):
    def setUp(self) -> None:
        self.stores = fake_stores()
        self.asks = self.stores.asks

    def test_the_new_fields_round_trip_and_an_ask_is_version_3(self) -> None:
        ask = dataclasses.replace(
            must(raiser.raise_ask(self.asks, question("requirement", "keep v1"), asking())[0]),
            cause_by="owner", similar=[SimilarRef(kind="adr", id="ADR-2"), SimilarRef(kind="ask", id="t-0-1")],
            thread=[ThreadEntry(by="owner", t=T, md="why?")], outcome=Stick.ADR, outcome_ref="ADR-3")
        wire = codec.to_json(ask)
        self.assertEqual(wire["v"], 3)
        self.assertEqual(codec.from_json(Ask, json.loads(json.dumps(wire))), ask)
        self.assertEqual((ask.owner_cause, ask.blocking, ask.default), (OwnerCause.REQUIREMENT, False, "keep v1"))

    def test_an_agent_declared_cause_outside_the_list_is_unknown(self) -> None:
        self.assertEqual(specs.declared("environment"), OwnerCause.ENVIRONMENT)
        self.assertEqual([specs.declared(x) for x in ("", None, "vibes")], [OwnerCause.UNKNOWN] * 3)
        a = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking())[0])
        self.assertEqual((a.owner_cause, a.cause_by, a.blocking, a.default), (OwnerCause.UNKNOWN, "agent", True, ""))

    def test_an_ask_file_of_version_2_is_absent_and_listed_as_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            asks = AskStore.at(cfg)
            old = codec.to_json(must(raiser.raise_ask(fake_stores().asks, question(), asking())[0])) | {"v": 2}
            cfg.ask("t-1").parent.mkdir(parents=True)
            cfg.ask("t-1").write_text(json.dumps(old))
            self.assertEqual((asks.get("t-1"), asks.orphans(), asks.live()), (None, ["t-1"], []))


@domain
class Ledger(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks
        self.beads = FakeBeads()
        self.verbs = intake.Intake(self.asks, self.beads, lambda: T + 5, "denis")

    def rows(self, ask: str = "t-1-1") -> list[tuple[str, str, str]]:
        return [(r.event, r.answer, r.outcome.value if r.outcome else "") for r in self.asks.history(ask)]

    def test_each_transition_appends_one_row_carrying_cause_and_outcome(self) -> None:
        a = must(raiser.raise_ask(self.asks, question("process"), asking())[0])
        self.assertEqual((a.id, self.rows()), ("t-1-1", [("raise", "", "")]))
        first = self.asks.history("t-1-1")[0]
        self.assertEqual((first.question, first.cause, first.cause_by, first.t, first.repo),
                         (a.decision, OwnerCause.PROCESS, "agent", T, "/r/demo"))
        self.beads.beads["t-1"] = Bead(id="t-1", title="x", status="blocked")
        self.verbs.answer("t-1", "text", "keep v1")
        self.assertEqual(self.verbs.cause("t-1", "t-1-1", "requirement"), "")
        self.asks.consume("t-1", T + 9)
        self.assertTrue(self.asks.stuck("t-1", "t-1-1", Stick.DEMOTE, "", T + 9))
        self.assertEqual([r[0] for r in self.rows()], ["raise", "answer", "cause", "consume", "demote"])
        last = self.asks.history("t-1-1")[-1]
        self.assertEqual((last.cause, last.cause_by, last.answer, last.outcome), (OwnerCause.REQUIREMENT, "owner", "keep v1", Stick.DEMOTE))

    def test_withdraw_close_and_amend_leave_rows(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        self.asks.withdraw("t-1", "t-1-1", "no longer applies", T + 1)
        raiser.raise_ask(self.asks, question(), asking("t-2"))
        self.assertTrue(self.asks.close("t-2", "t-2-1", "the bead is closed", T + 2))
        raiser.raise_ask(self.asks, question(), asking("t-3"))
        self.asks.answer("t-3", "t-3-1", AskAnswer(action="text", text="a", t=T + 3, by="x"))
        self.asks.amend("t-3", "t-3-1", AskAnswer(action="text", text="b", t=T + 3, by="x"))
        self.assertEqual([r[0] for r in self.rows("t-1-1")], ["raise", "withdraw"])
        self.assertEqual([r[0] for r in self.rows("t-2-1")], ["raise", "close"])
        self.assertEqual([r[:2] for r in self.rows("t-3-1")], [("raise", ""), ("answer", "a"), ("answer", "b")])

    def test_the_ledger_outlives_the_ask_a_newer_ask_replaces(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        raiser.raise_ask(self.asks, question(), asking())
        self.assertEqual(must(self.asks.get("t-1")).id, "t-1-2")
        self.assertEqual(len(self.asks.history("t-1-1")), 1)
        self.assertEqual(len(self.asks.rows()), 2)

    def test_the_ledger_file_is_not_an_ask_and_no_sweep_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigDir(tmp)
            asks = AskStore.at(cfg)
            raiser.raise_ask(asks, question(), asking())
            self.assertEqual((cfg.ask_ledger().parent, asks.orphans(), len(asks.rows())), (cfg.root, [], 1))
            sweeps.close_stale(asks, lambda _r: FakeBeads(), cfg.ask_marker("s"), T + 10 ** 7)
            self.assertEqual(len(asks.rows()), 1)


@domain
class Repeats(unittest.TestCase):
    def setUp(self) -> None:
        self.stores = fake_stores()
        self.asks = self.stores.asks
        self.adrs = self.stores.adrs("/r/demo")

    def test_the_key_is_the_class_and_the_significant_words_of_the_question(self) -> None:
        cls = question().ask_class
        self.assertEqual(similar.key_of(cls, Q), similar.key_of(cls, "Which save format should the engine KEEP for old files?!"))
        self.assertNotEqual(similar.key_of(cls, Q), similar.key_of(specs.missing_criteria().ask_class, Q))
        self.assertEqual(similar.key_of(cls, "the and for?"), "")

    def test_a_repeat_matches_a_past_answered_ask(self) -> None:
        first = must(raiser.raise_ask(self.asks, question(), asking("t-1"), self.adrs)[0])
        self.assertEqual(first.similar, [])
        again = must(raiser.raise_ask(self.asks, question(), asking("t-2", T + 50), self.adrs)[0])
        self.assertEqual(again.similar, [])  # the first was never answered: it teaches nothing
        intake.Intake(self.asks, FakeBeads(), lambda: T + 60, "denis").answer("t-2", "text", "keep v1")
        third = must(raiser.raise_ask(self.asks, question(), asking("t-3", T + 70), self.adrs)[0])
        self.assertEqual(third.similar, [SimilarRef(kind="ask", id="t-2-1")])
        self.assertEqual(self.asks.history("t-3-1")[0].similar, third.similar)  # the ledger keeps what matched
        other = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking("t-4"), self.adrs)[0])
        self.assertEqual(other.similar, [])

    def test_a_repeat_matches_a_decision_in_force_first(self) -> None:
        key = similar.key_of(question().ask_class, question().decision)
        made = self.adrs.add(Adr(id="", n=0, repo="/r/demo", text="keep v1", question=Q, answer="keep v1", ask="x-1", bead="x", key=key,
                                 t=T))
        got = must(raiser.raise_ask(self.asks, question(), asking("t-9"), self.adrs)[0])
        self.assertEqual(got.similar, [SimilarRef(kind="adr", id=made.id)])
        elsewhere = must(raiser.raise_ask(self.asks, question(), asking("t-8"), self.stores.adrs("/r/other"))[0])
        self.assertEqual(elsewhere.similar, [])  # another repo's decisions do not apply


@domain
class SoftAsks(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks

    def test_a_soft_ask_never_makes_the_run_wait_and_stays_open(self) -> None:
        a = must(raiser.raise_ask(self.asks, question("decision", "keep v1"), asking())[0])
        self.assertEqual((a.blocking, a.default, a.status), (False, "keep v1", AskStatus.OPEN))
        self.assertEqual(raiser.check(self.asks, "t-1", "h", False, T + 1), ("none", None))
        self.assertEqual(raiser.check(self.asks, "t-1", "changed", True, T + 2), ("none", None))  # not even a changed bead consumes it
        self.assertEqual(must(self.asks.get("t-1")).consumed, None)

    def test_a_soft_ask_is_not_parked_and_a_later_answer_is_used(self) -> None:
        raiser.raise_ask(self.asks, question("decision", "keep v1"), asking(repo="/nowhere"))
        marker = Path(tempfile.gettempdir()) / "no-marker-x"
        self.assertEqual(sweeps.park_stale(self.asks, lambda _r: FakeBeads(), marker, T + 10 ** 7, 0), [])
        intake.Intake(self.asks, FakeBeads(), lambda: T + 9, "denis").answer("t-1", "text", "migrate")
        state, got = raiser.check(self.asks, "t-1", "h", False, T + 10)
        self.assertEqual((state, must(must(got).answer).text), ("answer", "migrate"))

    def test_a_blocking_ask_still_waits(self) -> None:
        raiser.raise_ask(self.asks, question(), asking())
        self.assertEqual(raiser.check(self.asks, "t-1", "h", False, T + 1)[0], "wait")
