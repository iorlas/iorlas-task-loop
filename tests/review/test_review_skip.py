"""A stage whose every changed path is allow-listed is accepted without a review call; one other path means the review runs."""
import json
import sys
from pathlib import Path
from typing import Any

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T

from tlkernel.config import ReviewSkipConfig
from tltestkit.plans import BEAD, CLEAN, PLAN, WRITE

ALLOW = ReviewSkipConfig(tests=["f.txt"])


class ReviewSkip(Case):
    eng: Any
    store: Any
    setup_method: Any = T.EngineTest.setup_method
    teardown_method: Any = T.EngineTest.teardown_method
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
        assert (rc, self.reviews(s)) == (0, 1)

    def test_a_mechanical_middle_stage_is_not_reviewed_but_the_last_one_is(self):
        stage = PLAN["stages"][0]
        plan = dict(PLAN, stages=[stage, dict(stage, goal="again")])
        rc, s = self.go(ALLOW, plan, writes=2)
        assert (rc, self.reviews(s, 2)) == (0, 1)
        log = [json.loads(x) for x in Path(self.eng.log_path).read_text().splitlines() if x.strip()]
        ends = [r for r in log if r.get("step") == "review" and r.get("outcome") == "skipped"]
        assert [r["detail"] for r in ends] == ["tests"]

    def test_a_path_outside_the_list_is_reviewed(self):
        stage = PLAN["stages"][0]
        rc, s = self.go(ReviewSkipConfig(tests=["other.txt"]), dict(PLAN, stages=[stage, dict(stage, goal="again")]), writes=2)
        assert (rc, self.reviews(s, 2)) == (0, 2)

    def test_no_allow_list_is_reviewed(self):
        rc, s = self.go(None)
        assert (rc, self.reviews(s)) == (0, 1)
