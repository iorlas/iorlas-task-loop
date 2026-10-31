"""engine.review off|sampled and the label review-off: no reviewer call, a typed reason on the review step, and a deterministic
acceptance check on the last stage in place of the reviewer."""
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import BEAD, CLEAN, HAS_F, PLAN, WRITE, adhoc

from taskloop.domain.review import switch

CASE = {"criterion": "the file f.txt exists", "check": adhoc(HAS_F), "class": "test"}
COVERED = dict(PLAN, cases=[CASE])


class Switch(unittest.TestCase):
    def test_the_label_turns_it_off_and_nothing_turns_it_on(self):
        self.assertEqual(switch.mode("on", ["review-off"]), "off")
        self.assertEqual(switch.mode("sampled", []), "sampled")

    def test_sampled_reviews_every_nth_stage_and_the_last(self):
        got = [switch.reviews("sampled", stage=i, last=i == 4, every=3) for i in range(5)]
        self.assertEqual(got, [False, False, True, False, True])
        self.assertFalse(switch.reviews("off", stage=2, last=True, every=3))
        self.assertTrue(switch.reviews("on", stage=0, last=False, every=3))

    def test_an_acceptance_item_no_case_names_is_reported(self):
        items = [("A1", "f.txt exists"), ("A2", "the dashboard shows the mode")]
        self.assertEqual(switch.covered(items, ["the file f.txt exists"]), ["A2"])


class ReviewOff(unittest.TestCase):
    eng: Any
    store: Any
    setUp: Any = T.EngineTest.setUp
    tearDown: Any = T.EngineTest.tearDown
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, plan=COVERED, bead=BEAD, writes=1, **cfg):
        with self.store.stub(show=bead):
            answers = {"plan": [plan], "write": [WRITE] * writes, "review": [CLEAN] * writes}
            return self.run_engine(answers, **cfg)

    def reviews(self, s, writes=1):
        return len(s.prompts) - 1 - writes

    def log(self):
        return [json.loads(x) for x in Path(self.eng.log_path).read_text().splitlines() if x.strip()]

    def test_off_lands_without_a_reviewer_call_and_says_why(self):
        rc, s = self.go(review="off")
        self.assertEqual((rc, self.reviews(s)), (0, 0))
        ends = [r for r in self.log() if r.get("step") == "review" and r.get("outcome") == "skipped"]
        self.assertEqual([r["detail"] for r in ends], ["review-off"])
        start = next(r for r in self.log() if "worktree" in r and "review" in r)
        self.assertEqual(start["review"], "off")

    def test_the_label_overrides_an_on_profile(self):
        rc, s = self.go(bead=dict(BEAD, labels=["visual", "review-off"]))
        self.assertEqual((rc, self.reviews(s)), (0, 0))

    def test_on_still_reviews(self):
        rc, s = self.go()
        self.assertEqual((rc, self.reviews(s)), (0, 1))

    def test_an_acceptance_item_no_case_names_is_reviewed_after_all(self):
        rc, s = self.go(plan=PLAN, review="off")
        self.assertEqual((rc, self.reviews(s)), (0, 1))

    def test_sampled_skips_the_middle_stage_and_reviews_the_last(self):
        stage = PLAN["stages"][0]
        plan = dict(COVERED, stages=[stage, dict(stage, goal="again")])
        rc, s = self.go(plan=plan, writes=2, review="sampled", review_every=5)
        self.assertEqual((rc, self.reviews(s, 2)), (0, 1))
        ends = [r for r in self.log() if r.get("step") == "review" and r.get("outcome") == "skipped"]
        self.assertEqual([r["detail"] for r in ends], ["review-sampled"])


if __name__ == "__main__":
    unittest.main()
