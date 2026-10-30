"""Verify runs only on a visual bead (tl-7y6.7.5): another bead lands with its unchecked items in one follow-up bead tagged `follow-up`,
filed once; an item that names an acceptance criterion is still asked; the acceptance-mapping review is not skipped."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import BEAD, CLEAN, PLAN, WRITE, verdict

from taskloop.contracts.config import ReviewSkipConfig
from taskloop.contracts.ports import BeadQuery

PLAIN = dict(BEAD, labels=[])  # f.txt, "f.txt exists": nothing visual about it
GAP = {"what": "f.txt exists on a clean checkout", "kind": "checkable"}
CRITERION = {"what": "whether f.txt exists once the stage has run twice", "kind": "owner_decision"}
SETTLED = {"items": [verdict(1, "settled", evidence="\"x\"")]}


class VerifyVisual(T.LandReviewBase):
    def go(self, items, bead=PLAIN, verify=None, **cfg):
        answers = {"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=items)]}
        if verify:
            answers["verify"] = verify
        with self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create"]

    def test_a_bead_that_is_not_visual_runs_no_verify(self):
        rc, s = self.go([GAP])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])

    def test_its_unchecked_items_go_in_one_follow_up_tagged_follow_up(self):
        rc, _ = self.go([GAP, dict(GAP, what="f.txt exists after a restart")])
        self.assertEqual(rc, 0, self.blocked)
        (made,) = self.creates()
        self.assertIn("follow-up", made[made.index("--labels") + 1].split(","))
        self.assertIn("f.txt exists on a clean checkout", " ".join(made))
        self.assertIn("f.txt exists after a restart", " ".join(made))

    def test_the_land_summary_says_what_landed_unchecked(self):
        self.go([GAP])
        self.assertTrue([c for c in self.bd_calls if c[:2] == ("comments", "add") and "not a visual bead" in str(c[3])])

    def test_a_bead_with_no_unchecked_item_files_nothing(self):
        rc, s = self.go([])
        self.assertEqual((rc, self.creates(), len(s.calls)), (0, [], 3))

    def test_a_follow_up_an_earlier_run_filed_is_not_filed_again(self):
        old = {"id": "t-5", "title": "Check after landing t-1: 1 item(s) nobody verified", "labels": ["follow-up"]}
        self.store.put(old)
        rc, _ = self.go([GAP])
        self.assertEqual((rc, self.creates()), (0, []))
        self.assertEqual([b.id for b in self.store.find(BeadQuery(label="follow-up"))], ["t-5"])

    def test_an_item_that_names_an_acceptance_criterion_is_asked_not_filed(self):
        bead = dict(PLAIN, acceptance_criteria="- f.txt exists once the stage has run twice")
        rc, s = self.go([CRITERION, GAP], bead=bead)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("f.txt exists once the stage has run twice", str(self.ask()))

    def test_a_visual_bead_still_runs_verify(self):
        rc, s = self.go([GAP], bead=dict(BEAD, labels=["ui"]), verify=[SETTLED])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the last one is verify
        self.assertEqual(self.creates(), [])

    def test_visual_words_in_the_acceptance_run_verify(self):
        _, s = self.go([GAP], bead=dict(PLAIN, acceptance_criteria="a screenshot shows that f.txt exists"), verify=[SETTLED])
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "reviewer"])  # the last one is verify

    def test_a_non_visual_bead_still_gets_its_acceptance_mapping_review(self):
        rc, s = self.go([], skip_review=ReviewSkipConfig(tests=["f.txt"]))
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])


if __name__ == "__main__":
    unittest.main()
