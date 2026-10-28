"""app/asks on fakes: raise and consume, the sweeps, and the owner's typed verbs."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from support.narrow import must  # noqa: E402
from support.tiers import domain  # noqa: E402
from taskloop.adapters.fake_beads import FakeBeads  # noqa: E402
from taskloop.contracts.bead import Bead  # noqa: E402
from taskloop.contracts.enums import AskStatus  # noqa: E402
from taskloop.contracts.ports import NewBead  # noqa: E402
from taskloop.app.asks import intake, raiser, sweeps  # noqa: E402
from taskloop.domain.asks import specs  # noqa: E402
from taskloop.stores.memory import fake_stores  # noqa: E402

T = 1000.0


def asking(bead: str = "t-1", repo: str = "", now: float = T, brief: str = "h") -> raiser.Asking:
    return raiser.Asking(bead=bead, run="r", brief_hash=brief, repo=repo, title="T", now=now)


@domain
class RaiserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks

    def test_a_valid_ask_is_filed_and_numbered(self) -> None:
        a, problems = raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        a = must(a)
        self.assertEqual((problems, a.id, a.status, a.parks_at), ([], "t-1-1", AskStatus.OPEN, T + raiser.PARK_AFTER_S))
        b = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking())[0])
        self.assertEqual(b.id, "t-1-2")

    def test_an_invalid_ask_writes_nothing(self) -> None:
        bad = dataclasses.replace(specs.missing_criteria(), decision="not a question")
        a, problems = raiser.raise_ask(self.asks, bad, asking())
        self.assertEqual((a, self.asks.get("t-1")), (None, None))
        self.assertIn("decision: does not end in '?'", problems)

    def test_the_next_run_waits_while_nothing_changed_and_goes_on_when_answered_or_changed(self) -> None:
        self.assertEqual(raiser.check(self.asks, "t-1", "h", False, T), ("none", None))
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        self.assertEqual(raiser.check(self.asks, "t-1", "h", False, T)[0], "wait")
        self.assertEqual(raiser.check(self.asks, "t-1", "h", True, T)[0], "answer")  # --fresh
        self.assertEqual(raiser.check(self.asks, "t-1", "h", False, T), ("none", None))  # used once
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        kind, got = raiser.check(self.asks, "t-1", "changed", False, T + 5)
        ask = must(got)
        self.assertEqual((kind, ask.consumed, ask.answer), ("answer", T + 5, None))  # the bead changed: no AskAnswer, still an answer

    def test_a_filed_answer_is_used_even_when_the_bead_did_not_change(self) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        intake.Intake(self.asks, FakeBeads(), lambda: T + 1, "denis").answer("t-1", "rerun", "run again")
        kind, got = raiser.check(self.asks, "t-1", "h", False, T + 2)
        ask = must(got)
        self.assertEqual((kind, must(ask.answer).action, ask.consumed), ("answer", "rerun", T + 2))

    def test_leaving_the_queue_swaps_the_pick_label(self) -> None:
        store = FakeBeads()
        store.beads["t-1"] = Bead(id="t-1", title="T", status="open", labels=["auto"])
        self.assertIn("label auto removed, needs-info added", raiser.leave_queue(store, "t-1", "auto", "needs-info"))
        self.assertEqual(store.beads["t-1"].labels, ["needs-info"])
        self.assertEqual(store.beads["t-1"].metadata.get("had_pick_label"), "auto")  # recorded, so only this label is ever given back
        self.assertEqual(raiser.leave_queue(store, "t-1", "auto", "needs-info"), "")


@domain
class SweepTest(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / ".beads").mkdir()
        self.marker = self.repo / ".mark"
        self.store = FakeBeads()
        for b in ("open", "done"):
            self.store.create(NewBead(title=b))
        self.store.close("fk-2", "x")

    def raise_for(self, bead: str, now: float = T) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking(bead, str(self.repo), now))

    def test_asks_of_closed_or_missing_beads_are_closed_once_per_window(self) -> None:
        for b in ("fk-1", "fk-2", "fk-9"):
            self.raise_for(b)
        got = sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T)
        self.assertEqual(sorted(got), ["fk-2", "fk-9"])
        self.assertEqual(must(self.asks.get("fk-2")).closed_why, "the bead is closed")
        self.assertEqual(must(self.asks.get("fk-9")).closed_why, "the bead does not exist")
        self.assertEqual(must(self.asks.get("fk-1")).status, AskStatus.OPEN)
        self.assertEqual(sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T + 1), [])  # throttled

    def test_an_ask_with_no_known_tracker_stays(self) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking("fk-2", "/nowhere"))
        self.assertEqual(sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T), [])

    def test_late_unanswered_asks_are_parked_with_a_comment(self) -> None:
        self.raise_for("fk-1", T)
        self.assertEqual(sweeps.park_stale(self.asks, lambda r: self.store, self.marker, T + 10), [])
        marker = self.repo / ".mark2"
        late = T + raiser.PARK_AFTER_S + 1
        self.assertEqual(sweeps.park_stale(self.asks, lambda r: self.store, marker, late), ["fk-1"])
        self.assertEqual(must(self.asks.get("fk-1")).status, AskStatus.PARKED)
        self.assertIn("Parked (engine)", self.store.comments("fk-1")[0].text)

    def test_an_answer_no_run_used_for_30_minutes_is_a_fault(self) -> None:
        self.raise_for("fk-1")
        intake.Intake(self.asks, self.store, lambda: T + 10, "denis").answer("fk-1", "text", "do x")
        self.assertEqual(sweeps.unused_answers(self.asks, T + 20), [])
        late = sweeps.unused_answers(self.asks, T + 10 + sweeps.UNUSED_ANSWER_S + 1)
        self.assertEqual([a.bead for a in late], ["fk-1"])
        self.assertIn("answered 30 min ago", sweeps.fault_line(late[0], T + 10 + 1800))
        self.asks.consume("fk-1", T + 3000)
        self.assertEqual(sweeps.unused_answers(self.asks, T + 5000), [])


@domain
class IntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.asks = fake_stores().asks
        self.store = FakeBeads()
        self.store.create(NewBead(title="x"))
        self.store.update("fk-1", intake.BeadPatch(status="blocked"))
        self.verbs = intake.Intake(self.asks, self.store, lambda: T + 1, "denis")
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking("fk-1"))

    def test_an_answer_is_a_typed_record_the_first_wins_and_the_bead_opens(self) -> None:
        done, why = self.verbs.answer("fk-1", "text", " write it ")
        given = must(must(done).answer)
        self.assertEqual((why, given.action, given.text, given.by), ("", "text", "write it", "denis"))
        self.assertEqual(self.store.beads["fk-1"].status, "open")
        self.assertEqual(self.verbs.answer("fk-1", "rerun")[1], "answered")
        self.assertEqual(must(must(self.verbs.answer("fk-1", "rerun", "better", amend=True)[0]).answer).text, "better")
        self.assertEqual(self.verbs.answer("nope", "rerun")[1], "gone")

    def test_hint_hold_and_override_are_metadata_never_prose(self) -> None:
        self.verbs.hint("fk-1", " mind the cache ")
        self.verbs.hold("fk-1")
        self.verbs.override("fk-1", "replan-cap")
        self.assertEqual(self.store.beads["fk-1"].metadata, {intake.HINT: "mind the cache", intake.HOLD: "denis", intake.OVERRIDE: "replan-cap"})
        self.verbs.hold("fk-1", on=False)
        self.assertNotIn(intake.HOLD, self.store.beads["fk-1"].metadata)
        with self.assertRaises(ValueError):
            self.verbs.override("fk-1", "everything")

    def test_withdraw_drops_an_ask_no_run_used(self) -> None:
        done, why = self.verbs.withdraw("fk-1", "no longer applies")
        done = must(done)
        self.assertEqual((why, done.status, done.closed_why), ("", AskStatus.WITHDRAWN, "no longer applies"))


@domain
class ParseTest(unittest.TestCase):
    def test_only_a_receipt_of_ours_has_a_verb(self) -> None:
        r = intake.receipt("answer", "do x", ask="t-1-1", action="text")
        p = intake.parse(r)
        self.assertEqual((p.kind, p.fields, p.body), ("answer", {"ask": "t-1-1", "action": "text"}, "do x"))
        self.assertEqual(intake.parse(intake.receipt("hint", "a: b")).body, "a: b")

    def test_the_engines_comments_are_engine_and_everything_else_is_a_note(self) -> None:
        for t in ("Ask (engine) t-1-1 (decision): Which?", "Blocked: x", "Parked (engine): y", "Engine paused: z"):
            self.assertEqual(intake.parse(t).kind, "engine", t)
            self.assertTrue(intake.engine_written(t))
        for t in ("@answer right", "@hint use b", "hold this", "OVERRIDE: yes", "answer: land it", "", "Owner (tl) dance: x"):
            self.assertEqual(intake.parse(t).kind in ("note", "engine"), True, t)
            self.assertNotIn(intake.parse(t).kind, ("answer", "hint", "hold", "override", "decision"), t)
        self.assertTrue(intake.engine_written(intake.receipt("hint", "x")))


if __name__ == "__main__":
    unittest.main()
