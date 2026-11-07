"""Each stop of the engine builds an ask that passes lint, and the card text reads from the record's fields."""
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tiers import domain

from taskloop.app.asks.raiser import Asking, build
from taskloop.domain.asks import specs, text
from taskloop.domain.asks.lint import lint
from tlkernel.ask import AskAnswer, BudgetLine
from tlkernel.enums import AskClass
from tlkernel.ids import BeadId

AT = Asking(bead=BeadId("t-1"), run="t-1-20261026-101010", brief_hash="h", repo="/r", title="T", now=10.0)
LONG = "word " * 200


def ask_of(spec):
    return build(spec, 1, AT)


@domain
class SpecsTest(Case):
    def check(self, spec) -> None:
        assert lint(ask_of(spec)) == [], spec.decision

    def test_every_stop_builds_a_valid_ask(self) -> None:
        self.check(specs.over_budget(["189 of 180 min"], [BudgetLine(step="checks", minutes=124.0, rounds=21)], 5))
        self.check(specs.over_budget(["$16.00 of $15"], [], 0))
        self.check(specs.cap_reached(4, [("plan", "first plan"), ("amend", "the writer says the stage checks are wrong"), ("amend", LONG)]))
        self.check(specs.unproven(["the link works", "the build is reproducible"], 2))
        self.check(specs.no_progress("gate red on the rebased tree", 2, "line one\nthe last red line\n"))
        self.check(specs.no_progress("merge conflict with main", 2, ""))
        self.check(specs.external_fact(["a Windows build", LONG]))
        self.check(specs.missing_criteria())
        self.check(specs.too_big(["a", "b", "c", "d", "e", "f"], 5))
        self.check(specs.repeated_fault(3, "failed: engine error KeyError: 'x'"))

    def test_a_workers_question_is_fitted_not_dropped(self) -> None:
        sp = specs.open_question("PoseShots needs every slot. " + LONG + ". Should the content be a prerequisite or in scope?", [])
        self.check(sp)
        assert sp.decision == "Should the content be a prerequisite or in scope?"
        assert "PoseShots" in sp.detail.text
        self.check(specs.open_question(LONG + "?", None))
        assert specs.open_question("No question mark here", None).decision == "What should the engine do about this?"
        self.check(specs.open_question('Is {"a": 1} ok?\nreally?', []))

    def test_options_come_from_the_worker_recommended_first_and_are_made_up_to_two(self) -> None:
        given = [
            {"label": "B", "answer": "do b", "cost": "slow"},
            {"label": "A", "answer": "do a", "recommended": True},
            {"label": "", "answer": "x"},
        ]
        sp = specs.open_question("Which?", given)
        assert [(o.label, o.recommended, o.text) for o in sp.options] == [("A", True, "do a"), ("B", False, "do b")]
        one = specs.open_question("Which?", [{"label": "Only", "answer": "do it"}])
        assert ([o.label for o in one.options], one.options[0].recommended) == (["Only", "Split the bead"], True)
        self.check(one)
        assert len(specs.open_question("Which?", []).options) >= 2

    def test_replans_and_budget_lines_are_kept_as_fields(self) -> None:
        cap = ask_of(specs.cap_reached(3, [("plan", "first plan"), ("amend", "x")]))
        assert [(r.n, r.why) for r in cap.detail.replans] == [(1, "first plan"), (2, "x")]
        bud = ask_of(specs.over_budget(["a"], [BudgetLine(step="write", minutes=57.0, rounds=20)], 0))
        assert bud.detail.budget[0].rounds == 20


@domain
class TextTest(Case):
    def test_clip_cuts_at_a_word_and_marks_it(self) -> None:
        assert text.clip("a b c d", 5) == "a b…"

    def test_comment_lists_the_options_and_words_say_what_the_answer_asks(self) -> None:
        a = ask_of(specs.missing_criteria())
        assert "*I added them: " in text.comment(a)
        assert text.words(AskAnswer(action="text", text=" do x ")) == "do x"
        assert text.words(AskAnswer(action="split")) == text.SPLIT_WORDS
        assert (text.words(AskAnswer(action="rerun", text="run again")), text.words(None)) == ("", "")
        assert AskClass.MISSING_CRITERIA.value == a.ask_class.value
