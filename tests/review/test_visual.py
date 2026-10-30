"""Is a bead visual: the pure decision (domain/review/visual.py) over typed facts. Any doubt counts as visual."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.review import visual as v
from taskloop.domain.review.visual import VisualFacts, VisualWhy

BASE = VisualFacts(paths=["src/a.py"], labels=[], acceptance="the parser rejects a bad key", goals=["parse keys"], include=[], exclude=[],
                   look_item=False)


def facts(**kw: Any) -> VisualFacts:
    return replace(BASE, **kw)


class IsVisual(unittest.TestCase):
    def test_plain_code_with_plain_words_is_not_visual(self):
        self.assertEqual(v.why(facts()), ())
        self.assertFalse(v.is_visual(facts()))

    def test_a_declared_visual_path_hit_is_visual_unless_excluded(self):
        decl = {"include": ["web/**"], "exclude": ["web/test/**"]}
        self.assertEqual(v.why(facts(paths=["web/a.js"], **decl)), (VisualWhy.PATHS,))
        self.assertEqual(v.why(facts(paths=["web/test/a.js"], **decl)), ())

    def test_evidence_words_in_the_acceptance_are_visual(self):
        self.assertIn(VisualWhy.EVIDENCE, v.why(facts(acceptance="a screenshot shows the new layout")))

    def test_a_visual_label_is_visual(self):
        self.assertEqual(v.why(facts(labels=["ui"])), (VisualWhy.LABEL,))
        self.assertEqual(v.why(facts(labels=["slice-1", "stage"])), ())

    def test_a_stage_goal_that_names_a_look_is_visual(self):
        self.assertEqual(v.why(facts(goals=["change the header colour"])), (VisualWhy.STAGE,))

    def test_a_look_item_is_visual(self):
        self.assertEqual(v.why(facts(look_item=True)), (VisualWhy.LOOK,))

    def test_no_file_known_is_doubt_so_visual(self):
        self.assertEqual(v.why(facts(paths=[])), (VisualWhy.DOUBT,))

    def test_an_unknown_file_kind_is_doubt_unless_the_profile_declares_its_visual_paths(self):
        self.assertEqual(v.why(facts(paths=["a/b.xyz"])), (VisualWhy.DOUBT,))
        self.assertEqual(v.why(facts(paths=["a/b.png"])), (VisualWhy.DOUBT,))
        self.assertEqual(v.why(facts(paths=["a/b.xyz"], include=["web/**"])), ())

    def test_reasons_come_once_in_enum_order(self):
        got = v.why(facts(paths=[], labels=["ui"], acceptance="screenshot", look_item=True))
        self.assertEqual(got, (VisualWhy.EVIDENCE, VisualWhy.LABEL, VisualWhy.LOOK, VisualWhy.DOUBT))


class NamesCriterion(unittest.TestCase):
    AC = "- the parser rejects a bad key with a clear message\n- the dashboard lists every slot"

    def test_an_item_that_restates_a_criterion_names_it(self):
        self.assertTrue(v.names_criterion("whether the parser rejects a bad key with a clear message", self.AC))

    def test_an_unrelated_item_does_not(self):
        self.assertFalse(v.names_criterion("the retry delay was not measured on a slow disk", self.AC))

    def test_a_short_item_never_does(self):
        self.assertFalse(v.names_criterion("parser key", self.AC))


if __name__ == "__main__":
    unittest.main()
