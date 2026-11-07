"""Ask lint: the 8 quoted bad asks fail, the 3 rewrites pass, and each rule is one failing case."""
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tiers import domain

from asks import samples
from taskloop.domain.asks.lint import INFRA, KIND_OF, lint
from tlkernel.askenums import AskClass, AskKind

GOOD = samples.MOCKS["lifesim-22b3"]


@domain
class QuotedAsksTest(Case):
    def test_each_of_the_eight_bad_asks_fails(self) -> None:
        for bead, a in samples.BAD.items():
            assert lint(a), bead

    def test_the_three_rewrites_pass(self) -> None:
        for bead, a in samples.MOCKS.items():
            assert lint(a) == [], bead

    def test_infra_classes_never_become_asks(self) -> None:
        for cls in INFRA:
            assert "never an ask" in " ".join(lint(GOOD.replace(ask_class=cls))), cls
        assert set(AskClass) - INFRA == {cls for cls, kind in KIND_OF.items() if kind is not None}


@domain
class RuleTest(Case):
    def problems(self, **kw) -> str:
        return " | ".join(lint(GOOD.replace(**kw)))

    def test_decision_is_one_short_sentence_that_asks(self) -> None:
        assert "does not end" in self.problems(decision="Run again.")
        assert "at most 120" in self.problems(decision="Why " * 40 + "?")
        assert "more than one sentence" in self.problems(decision="It broke. Run again?")
        assert "more than one sentence" in self.problems(decision="Run\nagain?")
        assert "payload" in self.problems(decision='Is {"a": 1} fine?')

    def test_what_was_tried_is_three_bullets_at_most(self) -> None:
        assert "at most 3" in self.problems(tried=["a", "b", "c", "d"])
        assert "empty" in self.problems(tried=[" "])

    def test_two_to_five_options_each_with_a_consequence_recommended_first(self) -> None:
        o = GOOD.options
        assert "need 2 to 5" in self.problems(options=o[:1])
        assert "need 2 to 5" in self.problems(options=o * 3)
        assert "not first" in self.problems(options=[o[1], o[0]])
        assert "more than one" in self.problems(options=[o[0], o[1].replace(recommended=True)])
        assert "no consequence" in self.problems(options=[o[0], o[1].replace(consequence="")])
        assert "share a label" in self.problems(options=[o[0], o[1].replace(label=o[0].label)])

    def test_the_class_matches_the_kind(self) -> None:
        assert "not a stuck ask" in self.problems(kind=AskKind.STUCK, ask_class=AskClass.OPEN_QUESTION)
