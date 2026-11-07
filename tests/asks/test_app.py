"""app/asks on fakes: raise and consume, the sweeps, and the owner's typed verbs."""
import dataclasses
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.memstores import fake_stores
from support.narrow import must
from support.tiers import domain

from taskloop.adapters.bd import BdRun, BdStore
from taskloop.app.asks import intake, raiser, sweeps
from taskloop.domain.asks import specs
from taskloop.domain.asks.lint import INFRA
from tlkernel.askenums import AskKind, AskStatus
from tlkernel.bead import Bead
from tlkernel.beadsport import NewBead
from tlkernel.ids import BeadId

T = 1000.0


def asking(bead: str = "t-1", repo: str = "", now: float = T, brief: str = "h") -> raiser.Asking:
    return raiser.Asking(bead=BeadId(bead), run="r", brief_hash=brief, repo=repo, title="T", now=now)


@domain
class RaiserTest(Case):
    def setup_method(self) -> None:
        self.asks = fake_stores().asks

    def test_a_valid_ask_is_filed_and_numbered(self) -> None:
        a, problems = raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        a = must(a)
        assert (problems, a.id, a.status, a.parks_at) == ([], "t-1-1", AskStatus.OPEN, T + raiser.PARK_AFTER_S)
        b = must(raiser.raise_ask(self.asks, specs.missing_criteria(), asking())[0])
        assert b.id == "t-1-2"

    def test_an_invalid_ask_writes_nothing(self) -> None:
        bad = dataclasses.replace(specs.missing_criteria(), decision="not a question")
        a, problems = raiser.raise_ask(self.asks, bad, asking())
        assert (a, self.asks.get(BeadId("t-1"))) == (None, None)
        assert "decision: does not end in '?'" in problems

    def test_infrastructure_specs_are_refused_before_an_ask_is_built(self) -> None:
        for classification in INFRA:
            with self.subTest(classification=classification):
                spec = dataclasses.replace(specs.missing_criteria(), ask_class=classification)
                with pytest.raises(ValueError, match="never an ask"):
                    raiser.build(spec, 1, asking())
                assert "never an ask" in " ".join(raiser.problems(spec))
                ask, problems = raiser.raise_ask(self.asks, spec, asking())
                assert ask is None
                assert "never an ask" in " ".join(problems)
        assert self.asks.rows() == []

    def test_the_next_run_waits_while_nothing_changed_and_goes_on_when_answered_or_changed(self) -> None:
        assert raiser.check(self.asks, BeadId("t-1"), "h", False, T) == ("none", None)
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        assert raiser.check(self.asks, BeadId("t-1"), "h", False, T)[0] == "wait"
        assert raiser.check(self.asks, BeadId("t-1"), "h", True, T)[0] == "answer"  # --fresh
        assert raiser.check(self.asks, BeadId("t-1"), "h", False, T) == ("none", None)  # used once
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        kind, got = raiser.check(self.asks, BeadId("t-1"), "changed", False, T + 5)
        ask = must(got)
        assert (kind, ask.consumed, ask.answer) == ("answer", T + 5, None)  # the bead changed: no AskAnswer, still an answer

    def test_a_filed_answer_is_used_even_when_the_bead_did_not_change(self) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking())
        intake.Intake(self.asks, FakeBeads(), lambda: T + 1, "denis").answer(BeadId("t-1"), "rerun", "run again")
        kind, got = raiser.check(self.asks, BeadId("t-1"), "h", False, T + 2)
        ask = must(got)
        assert (kind, must(ask.answer).action, ask.consumed) == ("answer", "rerun", T + 2)

    def test_leaving_the_queue_swaps_the_pick_label(self) -> None:
        store = FakeBeads()
        store.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="T", status="open", labels=["auto"])
        assert "label auto removed, needs-info added" in raiser.leave_queue(store, BeadId("t-1"), "auto", "needs-info")
        assert store.beads[BeadId("t-1")].labels == ["needs-info"]
        assert store.beads[BeadId("t-1")].metadata.get("had_pick_label") == "auto"  # recorded: only this label is given back
        assert raiser.leave_queue(store, BeadId("t-1"), "auto", "needs-info") == ""


@domain
class SweepTest(Case):
    def setup_method(self) -> None:
        self.asks = fake_stores().asks
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / ".beads").mkdir()
        self.marker = self.repo / ".mark"
        self.store = FakeBeads()
        for b in ("open", "done"):
            self.store.create(NewBead(title=b))
        self.store.close(BeadId("fk-2"), "x")

    def raise_for(self, bead: str, now: float = T) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking(bead, str(self.repo), now))

    def test_asks_of_closed_or_missing_beads_are_closed_once_per_window(self) -> None:
        for b in ("fk-1", "fk-2", "fk-9"):
            self.raise_for(b)
        got = sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T)
        assert sorted(got) == ["fk-2", "fk-9"]
        assert must(self.asks.get(BeadId("fk-2"))).closed_why == "the bead is closed"
        assert must(self.asks.get(BeadId("fk-9"))).closed_why == "the bead does not exist"
        assert must(self.asks.get(BeadId("fk-1"))).status == AskStatus.OPEN
        assert sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T + 1) == []  # throttled

    def test_an_ask_with_no_known_tracker_stays(self) -> None:
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking("fk-2", "/nowhere"))
        assert sweeps.close_stale(self.asks, lambda r: self.store, self.marker, T) == []

    def test_malformed_show_after_nonempty_list_preserves_the_omitted_ask(self) -> None:
        self.raise_for("fk-9")
        before = self.asks.get(BeadId("fk-9"))
        for n, output in enumerate(("truncated", '{"issues": []}', '[{"id": "fk-9"}, {}]')):
            with self.subTest(output=output):
                calls: list[str] = []

                def run(argv: list[str], cwd: str | None, output: str = output, calls: list[str] = calls) -> BdRun:
                    calls.append(argv[3])
                    return BdRun(0, '[{"id": "fk-1", "status": "open"}]' if argv[3] == "list" else output, "")

                store = BdStore("x", exe="bd", run=run)
                marker = self.repo / f".malformed-{n}"
                assert sweeps.close_stale(self.asks, lambda r, store=store: store, marker, T) == []
                assert calls == ["list", "show"]
                assert self.asks.get(BeadId("fk-9")) == before

    def test_late_unanswered_asks_are_parked_with_a_comment(self) -> None:
        self.raise_for("fk-1", T)
        assert sweeps.park_stale(self.asks, lambda r: self.store, self.marker, T + 10) == []
        marker = self.repo / ".mark2"
        late = T + raiser.PARK_AFTER_S + 1
        assert sweeps.park_stale(self.asks, lambda r: self.store, marker, late) == ["fk-1"]
        assert must(self.asks.get(BeadId("fk-1"))).status == AskStatus.PARKED
        assert "Parked (engine)" in self.store.comments(BeadId("fk-1"))[0].text

    def test_an_answer_no_run_used_for_30_minutes_is_a_fault(self) -> None:
        self.raise_for("fk-1")
        intake.Intake(self.asks, self.store, lambda: T + 10, "denis").answer(BeadId("fk-1"), "text", "do x")
        assert sweeps.unused_answers(self.asks, T + 20) == []
        late = sweeps.unused_answers(self.asks, T + 10 + sweeps.UNUSED_ANSWER_S + 1)
        assert [a.bead for a in late] == ["fk-1"]
        assert "answered 30m ago" in sweeps.fault_line(late[0], T + 10 + 1800)
        self.asks.consume(BeadId("fk-1"), T + 3000)
        assert sweeps.unused_answers(self.asks, T + 5000) == []


@domain
class IntakeTest(Case):
    def setup_method(self) -> None:
        self.asks = fake_stores().asks
        self.store = FakeBeads()
        self.store.create(NewBead(title="x"))
        self.store.update(BeadId("fk-1"), intake.BeadPatch(status="blocked"))
        self.verbs = intake.Intake(self.asks, self.store, lambda: T + 1, "denis")
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking("fk-1"))

    def test_an_answer_is_a_typed_record_the_first_wins_and_the_bead_opens(self) -> None:
        done, why = self.verbs.answer(BeadId("fk-1"), "text", " write it ")
        given = must(must(done).answer)
        assert (why, given.action, given.text, given.by) == ("", "text", "write it", "denis")
        assert self.store.beads[BeadId("fk-1")].status == "open"
        assert self.verbs.answer(BeadId("fk-1"), "rerun")[1] == "answered"
        assert must(must(self.verbs.answer(BeadId("fk-1"), "rerun", "better", amend=True)[0]).answer).text == "better"
        assert self.verbs.answer(BeadId("nope"), "rerun")[1] == "gone"

    def test_the_answer_to_a_decision_ask_is_a_comment_that_says_kind_decision_and_another_kind_does_not(self) -> None:
        kinds = {}
        for bead, spec in (("fk-1", specs.missing_criteria()), ("fk-2", specs.open_question("Which way?", None))):
            if bead == "fk-2":
                self.store.create(NewBead(title="y"))
                raiser.raise_ask(self.asks, spec, asking(bead))
            kinds[bead] = must(self.asks.get(BeadId(bead))).kind
            self.verbs.answer(BeadId(bead), "text", "go")
        assert len(set(kinds.values())) == 2 and AskKind.DECISION in kinds.values()
        for bead, kind in kinds.items():
            text = self.store.comments(BeadId(bead))[-1].text
            assert ("kind=decision" in text) == (kind is AskKind.DECISION), (bead, kind, text)

    def test_an_answer_naming_a_replaced_ask_is_refused_and_files_nothing(self) -> None:
        old = must(self.asks.get(BeadId("fk-1"))).id
        raiser.raise_ask(self.asks, specs.missing_criteria(), asking("fk-1"))  # the engine asked again: a new ask id
        assert must(self.asks.get(BeadId("fk-1"))).id != old
        _done, why = self.verbs.answer(BeadId("fk-1"), "text", "for the old one", expect=old)
        assert (why, must(self.asks.get(BeadId("fk-1"))).answer, self.store.beads[BeadId("fk-1")].status) == ("superseded", None, "blocked")
        current = must(self.asks.get(BeadId("fk-1"))).id
        assert self.verbs.answer(BeadId("fk-1"), "text", "for the new one", expect=current)[1] == ""

    def test_hint_hold_and_override_are_metadata_never_prose(self) -> None:
        self.verbs.hint(BeadId("fk-1"), " mind the cache ")
        self.verbs.hold(BeadId("fk-1"))
        self.verbs.override(BeadId("fk-1"), "replan-cap")
        assert (
            self.store.beads[BeadId("fk-1")].metadata
            == {intake.HINT: "mind the cache", intake.HOLD: "denis", intake.OVERRIDE: "replan-cap"}
        )
        self.verbs.hold(BeadId("fk-1"), on=False)
        assert intake.HOLD not in self.store.beads[BeadId("fk-1")].metadata
        with pytest.raises(ValueError):
            self.verbs.override(BeadId("fk-1"), "everything")

    def test_withdraw_drops_an_ask_no_run_used(self) -> None:
        done, why = self.verbs.withdraw(BeadId("fk-1"), "no longer applies")
        done = must(done)
        assert (why, done.status, done.closed_why) == ("", AskStatus.WITHDRAWN, "no longer applies")


@domain
class ParseTest(Case):
    def test_only_a_receipt_of_ours_has_a_verb(self) -> None:
        r = intake.receipt("answer", "do x", ask="t-1-1", action="text")
        p = intake.parse(r)
        assert (p.kind, p.fields, p.body) == ("answer", {"ask": "t-1-1", "action": "text"}, "do x")
        assert intake.parse(intake.receipt("hint", "a: b")).body == "a: b"

    def test_comment_text_does_not_identify_its_author(self) -> None:
        for t in ("Ask (engine) t-1-1 (decision): Which?", "Blocked: x", "Parked (engine): y", "Engine paused: z"):
            assert intake.parse(t).kind == "note", t
        for t in ("@answer right", "@hint use b", "hold this", "OVERRIDE: yes", "answer: land it", "", "Owner (tl) dance: x"):
            assert (intake.parse(t).kind in ("note", "engine")) is True, t
            assert intake.parse(t).kind not in ("answer", "hint", "hold", "override", "decision"), t


class AskArtifacts(Case):
    def test_the_pictures_a_stop_names_go_on_the_filed_ask(self):
        asks = fake_stores().asks
        at = dataclasses.replace(asking(), artifacts=("r-1/t-1/r/ask-1/skin-cheek.png",))
        ask = must(raiser.raise_ask(asks, specs.missing_criteria(), at)[0])
        assert ask.artifacts == ["r-1/t-1/r/ask-1/skin-cheek.png"]
        assert must(asks.get(ask.bead)).artifacts == ask.artifacts

    def test_an_ask_without_pictures_has_none(self):
        ask = must(raiser.raise_ask(fake_stores().asks, specs.missing_criteria(), asking())[0])
        assert ask.artifacts == []
