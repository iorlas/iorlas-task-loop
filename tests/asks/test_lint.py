"""Ask lint: the 8 quoted bad asks fail, the 3 rewrites pass, and each rule is one failing case."""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tiers import domain

from asks import samples
from taskloop.contracts.enums import AskClass, AskKind
from taskloop.domain.asks.lint import INFRA, KIND_OF, lint

GOOD = samples.MOCKS["lifesim-22b3"]


@domain
class QuotedAsksTest(unittest.TestCase):
    def test_each_of_the_eight_bad_asks_fails(self) -> None:
        for bead, a in samples.BAD.items():
            self.assertTrue(lint(a), bead)

    def test_the_three_rewrites_pass(self) -> None:
        for bead, a in samples.MOCKS.items():
            self.assertEqual(lint(a), [], bead)

    def test_infra_classes_never_become_asks(self) -> None:
        for cls in INFRA:
            self.assertIn("never an ask", " ".join(lint(dataclasses.replace(GOOD, ask_class=cls))), cls)
        self.assertEqual(set(AskClass) - INFRA, set(KIND_OF))


@domain
class RuleTest(unittest.TestCase):
    def problems(self, **kw) -> str:
        return " | ".join(lint(dataclasses.replace(GOOD, **kw)))

    def test_decision_is_one_short_sentence_that_asks(self) -> None:
        self.assertIn("does not end", self.problems(decision="Run again."))
        self.assertIn("at most 120", self.problems(decision="Why " * 40 + "?"))
        self.assertIn("more than one sentence", self.problems(decision="It broke. Run again?"))
        self.assertIn("more than one sentence", self.problems(decision="Run\nagain?"))
        self.assertIn("payload", self.problems(decision='Is {"a": 1} fine?'))

    def test_what_was_tried_is_three_bullets_at_most(self) -> None:
        self.assertIn("at most 3", self.problems(tried=["a", "b", "c", "d"]))
        self.assertIn("empty", self.problems(tried=[" "]))

    def test_two_to_five_options_each_with_a_consequence_recommended_first(self) -> None:
        o = GOOD.options
        self.assertIn("need 2 to 5", self.problems(options=o[:1]))
        self.assertIn("need 2 to 5", self.problems(options=o * 3))
        self.assertIn("not first", self.problems(options=[o[1], o[0]]))
        self.assertIn("more than one", self.problems(options=[o[0], dataclasses.replace(o[1], recommended=True)]))
        self.assertIn("no consequence", self.problems(options=[o[0], dataclasses.replace(o[1], consequence="")]))
        self.assertIn("share a label", self.problems(options=[o[0], dataclasses.replace(o[1], label=o[0].label)]))

    def test_the_class_matches_the_kind(self) -> None:
        self.assertIn("not a stuck ask", self.problems(kind=AskKind.STUCK, ask_class=AskClass.OPEN_QUESTION))


if __name__ == "__main__":
    unittest.main()
