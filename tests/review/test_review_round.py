"""The review step end to end on the fake route: what sends a stage back, what the engine files instead, the acceptance items of the
last stage, and the round rules of the prompt."""
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as T
from support.engine_case import BEAD, CLEAN, WRITE, finding, review
from support.engine_case import FAST_PLAN as PLAN


class ReviewRound(unittest.TestCase):
    eng: Any
    store: Any
    setUp: Any = T.EngineTest.setUp
    tearDown: Any = T.EngineTest.tearDown
    commit_base_cfg: Any = T.EngineTest.commit_base_cfg
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine
    ask: Any = T.EngineTest.ask

    def go(self, reviews, writes=2, bead=BEAD):
        with self.store.stub(show=bead):
            return self.run_engine({"plan": [PLAN], "write": [WRITE] * writes, "review": reviews})

    def workers(self, s):
        return [c[0] for c in s.calls].count("worker")

    def test_a_high_finding_with_a_scenario_sends_the_stage_back(self):
        rc, s = self.go([review(findings=[finding("high")]), CLEAN])
        self.assertEqual((rc, self.workers(s)), (0, 2))
        self.assertIn("scenario: input x gives y", s.prompts[3])

    def test_a_medium_finding_and_a_high_one_without_a_scenario_are_notes(self):
        rc, s = self.go([review(findings=[finding("medium"), dict(finding("high"), scenario="")])], writes=1)
        self.assertEqual((rc, self.workers(s)), (0, 1))

    def test_a_demand_for_a_bead_is_filed_by_the_engine_not_sent_back(self):
        rc, s = self.go([review(unmet=["approval + follow-up beads unfiled"], findings=[dict(finding("high"), fix="close the bead")])],
                        writes=1)
        self.assertEqual((rc, self.workers(s)), (0, 1))
        self.assertEqual(len(self.eng.leftovers), 2)

    def test_goal_is_met_in_unmet_is_no_gap(self):
        rc, s = self.go([review(unmet=["the stage goal is met"])], writes=1)
        self.assertEqual((rc, self.workers(s)), (0, 1))

    def test_an_unmapped_acceptance_item_sends_the_last_stage_back(self):
        bead = dict(BEAD, acceptance_criteria="- f.txt exists\n- the log says done")
        none = dict(CLEAN, criteria=[{"item": "A1", "status": "met", "evidence": "check"}])
        rc, s = self.go([none, CLEAN], bead=bead)  # CLEAN gets every listed item mapped by the fake route
        self.assertEqual((rc, self.workers(s)), (0, 2))
        self.assertIn("A2", s.prompts[3])

    def test_the_prompt_states_the_host_and_the_round_rules(self):
        _rc, s = self.go([review(findings=[finding("high")]), CLEAN])
        first, second = s.prompts[2], s.prompts[4]
        for text in (first, second):
            self.assertIn("The host is macOS", text)
            self.assertIn("Only the coordinator can run bd", text)
        self.assertIn("complete list of its blocking findings", first)
        self.assertIn("review round 2", second)
        self.assertIn("A1. f.txt exists", first)


if __name__ == "__main__":
    unittest.main()
