"""A stage whose every changed path is allow-listed is accepted without a review call; one other path means the review runs."""
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import BEAD, CLEAN, PLAN, WRITE

from taskloop.contracts.config import ReviewSkipConfig

ALLOW = ReviewSkipConfig(tests=["f.txt"])


class ReviewSkip(unittest.TestCase):
    eng: Any
    store: Any
    setUp: Any = T.EngineTest.setUp
    tearDown: Any = T.EngineTest.tearDown
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, cfg, plan=PLAN, writes=1):
        with self.store.stub(show=BEAD):
            answers = {"plan": [plan], "write": [WRITE] * writes, "review": [CLEAN] * writes}
            return self.run_engine(answers, **({"skip_review": cfg} if cfg else {}))

    def reviews(self, s, writes=1):
        return len(s.prompts) - 1 - writes

    def test_a_single_stage_tests_only_bead_is_reviewed(self):
        rc, s = self.go(ALLOW)
        self.assertEqual((rc, self.reviews(s)), (0, 1))

    def test_a_mechanical_middle_stage_is_not_reviewed_but_the_last_one_is(self):
        stage = PLAN["stages"][0]
        plan = dict(PLAN, stages=[stage, dict(stage, goal="again")])
        rc, s = self.go(ALLOW, plan, writes=2)
        self.assertEqual((rc, self.reviews(s, 2)), (0, 1))
        log = [json.loads(x) for x in Path(self.eng.log_path).read_text().splitlines() if x.strip()]
        ends = [r for r in log if r.get("step") == "review" and r.get("outcome") == "skipped"]
        self.assertEqual([r["detail"] for r in ends], ["tests"])

    def test_a_path_outside_the_list_is_reviewed(self):
        stage = PLAN["stages"][0]
        rc, s = self.go(ReviewSkipConfig(tests=["other.txt"]), dict(PLAN, stages=[stage, dict(stage, goal="again")]), writes=2)
        self.assertEqual((rc, self.reviews(s, 2)), (0, 2))

    def test_no_allow_list_is_reviewed(self):
        rc, s = self.go(None)
        self.assertEqual((rc, self.reviews(s)), (0, 1))


if __name__ == "__main__":
    unittest.main()
