"""Review switches affect intermediate stages; the final acceptance review always runs."""
import json
import sys
from pathlib import Path
from typing import Any

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import adhoc
from support.plans import BEAD, CLEAN, HAS_F, PLAN, WRITE, review

from taskloop.domain.review import switch

CASE = {"criterion": "the file f.txt exists", "check": adhoc(HAS_F), "class": "test"}
COVERED = dict(PLAN, cases=[CASE])


class Switch(Case):
    def test_the_label_turns_it_off_and_nothing_turns_it_on(self):
        assert switch.mode("on", ["review-off"]) == "off"
        assert switch.mode("sampled", []) == "sampled"

    def test_sampled_reviews_every_nth_stage_and_the_last(self):
        got = [switch.reviews("sampled", stage=i, last=i == 4, every=3) for i in range(5)]
        assert got == [False, False, True, False, True]
        assert switch.reviews("off", stage=2, last=True, every=3)
        assert not switch.reviews("off", stage=0, last=False, every=3)
        assert switch.reviews("on", stage=0, last=False, every=3)

    def test_every_mode_requires_the_final_review(self):
        for mode in ("on", "off", "sampled"):
            with self.subTest(mode=mode):
                assert switch.reviews(mode, stage=0, last=True, every=5)


class ReviewOff(Case):
    eng: Any
    store: Any
    setup_method: Any = T.EngineTest.setup_method
    teardown_method: Any = T.EngineTest.teardown_method
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, plan=COVERED, bead=BEAD, writes=1, reviews=None, **cfg):
        with self.store.stub(show=bead):
            answers = {"plan": [plan], "write": [WRITE] * writes, "review": reviews if reviews is not None else [CLEAN] * writes}
            return self.run_engine(answers, **cfg)

    def reviews(self, s, writes=1):
        return len(s.prompts) - 1 - writes

    def log(self):
        return [json.loads(x) for x in Path(self.eng.log_path).read_text().splitlines() if x.strip()]

    def test_off_requires_a_final_reviewer_even_when_cases_name_acceptance(self):
        rc, s = self.go(review="off")
        assert (rc, self.reviews(s)) == (0, 1)
        ends = [r for r in self.log() if r.get("step") == "review" and r.get("outcome") == "skipped"]
        assert ends == []
        start = next(r for r in self.log() if "worktree" in r and "review" in r)
        assert start["review"] == "off"

    def test_the_label_cannot_remove_final_review_from_an_on_profile(self):
        rc, s = self.go(bead=dict(BEAD, labels=["visual", "review-off"]))
        assert (rc, self.reviews(s)) == (0, 1)

    def test_negated_criterion_and_unrelated_green_check_cannot_bypass_reviewer(self):
        acceptance = "Account deletion preserves audit history"
        case = dict(CASE, criterion="Account deletion removes audit history")
        rc, s = self.go(plan=dict(PLAN, cases=[case]), bead=dict(BEAD, acceptance_criteria=acceptance),
                        reviews=[review(question="Should account deletion preserve audit history?")], review="off")
        assert (rc, self.reviews(s)) == (2, 1)
        assert not self.eng.landed_sha
        assert acceptance in s.prompts[-1]
        assert case["criterion"] in s.prompts[-1]

    def test_empty_acceptance_is_blocked_at_the_ticket_not_skipped_by_review_off(self):
        rc, _ = self.go(bead=dict(BEAD, acceptance_criteria=""), review="off")
        assert rc == 2

    def test_off_skips_only_intermediate_stages(self):
        stage = PLAN["stages"][0]
        plan = dict(COVERED, stages=[stage, dict(stage, goal="again")])
        rc, s = self.go(plan=plan, writes=2, review="off")
        assert (rc, self.reviews(s, 2)) == (0, 1)
        ends = [r for r in self.log() if r.get("step") == "review" and r.get("outcome") == "skipped"]
        assert [r["detail"] for r in ends] == ["review-off"]

    def test_on_still_reviews(self):
        rc, s = self.go()
        assert (rc, self.reviews(s)) == (0, 1)

    def test_an_acceptance_item_no_case_names_is_reviewed_after_all(self):
        rc, s = self.go(plan=PLAN, review="off")
        assert (rc, self.reviews(s)) == (0, 1)

    def test_sampled_skips_the_middle_stage_and_reviews_the_last(self):
        stage = PLAN["stages"][0]
        plan = dict(COVERED, stages=[stage, dict(stage, goal="again")])
        rc, s = self.go(plan=plan, writes=2, review="sampled", review_every=5)
        assert (rc, self.reviews(s, 2)) == (0, 1)
        ends = [r for r in self.log() if r.get("step") == "review" and r.get("outcome") == "skipped"]
        assert [r["detail"] for r in ends] == ["review-sampled"]
