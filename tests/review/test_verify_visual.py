"""Verify runs only on a visual bead (tl-7y6.7.5): another bead lands with its unchecked items in one follow-up bead tagged `follow-up`,
filed once; an item that names an acceptance criterion is still asked; the acceptance-mapping review is not skipped."""
from support.engine_land import LandReviewBase

from tlkernel.beadsport import BeadQuery
from tlkernel.config import ReviewSkipConfig
from tlkernel.followkeys import key_label, unchecked
from tltestkit.plans import BEAD, CLEAN, PLAN, WRITE, verdict

PLAIN = dict(BEAD, labels=[])  # f.txt, "f.txt exists": nothing visual about it
NOT_VISUAL = dict(PLAN, cases=[])  # no look-objective, taste or show case: the planner says nothing is to be seen
GAP = {"what": "f.txt exists on a clean checkout", "kind": "checkable"}
CRITERION = {"what": "whether f.txt exists once the stage has run twice", "kind": "owner_decision"}
SETTLED = {"items": [verdict(1, "settled", evidence="\"x\"")]}


class VerifyVisual(LandReviewBase):
    def go(self, items, bead=PLAIN, verify=None, plan=NOT_VISUAL, **cfg):
        answers = {"plan": [plan], "write": [WRITE], "review": [dict(CLEAN, unchecked=items)]}
        if verify:
            answers["verify"] = verify
        with self.store.stub(show=bead):
            return self.run_engine(answers, **cfg)

    def creates(self):
        return [c for c in self.bd_calls if c[0] == "create"]

    def test_a_bead_that_is_not_visual_runs_no_verify(self):
        rc, s = self.go([GAP])
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]

    def test_its_unchecked_items_go_in_one_follow_up_tagged_follow_up(self):
        rc, _ = self.go([GAP, dict(GAP, what="f.txt exists after a restart")])
        assert rc == 0, self.blocked
        (made,) = self.creates()
        assert "follow-up" in made[made.index("--labels") + 1].split(",")
        assert "f.txt exists on a clean checkout" in " ".join(made)
        assert "f.txt exists after a restart" in " ".join(made)

    def test_the_land_summary_says_what_landed_unchecked(self):
        self.go([GAP])
        assert [c for c in self.bd_calls if c[:2] == ("comments", "add") and "not a visual bead" in str(c[3])]

    def test_a_bead_with_no_unchecked_item_files_nothing(self):
        rc, s = self.go([])
        assert (rc, self.creates(), len(s.calls)) == (0, [], 3)

    def test_a_follow_up_an_earlier_run_filed_is_not_filed_again(self):
        old = {"id": "t-5", "title": "Check after landing t-1: 1 item(s) nobody verified",
               "labels": ["follow-up", key_label("t-1", unchecked("t-1", [GAP]))]}
        self.store.put(old)
        rc, _ = self.go([GAP])
        assert (rc, self.creates()) == (0, [])
        assert [b.id for b in self.store.find(BeadQuery(label="follow-up"))] == ["t-5"]

    def test_a_matching_title_without_the_exact_key_does_not_hide_pending_work(self):
        self.store.put({"id": "t-5", "title": "Check after landing t-1: unrelated", "labels": ["follow-up"]})
        rc, _ = self.go([GAP])
        assert (rc, len(self.creates())) == (0, 1)

    def test_an_item_that_names_an_acceptance_criterion_is_asked_not_filed(self):
        bead = dict(PLAIN, acceptance_criteria="- f.txt exists once the stage has run twice")
        rc, s = self.go([CRITERION, GAP], bead=bead)
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "f.txt exists once the stage has run twice" in str(self.ask())

    def test_a_visual_bead_still_runs_verify(self):
        rc, s = self.go([GAP], plan=PLAN, verify=[SETTLED])
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer", "reviewer"]  # the last one is verify
        assert self.creates() == []

    def test_visual_words_and_labels_no_longer_decide_only_the_plan_does(self):
        bead = dict(PLAIN, labels=["ui"], acceptance_criteria="a screenshot shows that f.txt exists")
        _, s = self.go([GAP], bead=bead)
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]

    def test_a_non_visual_bead_still_gets_its_acceptance_mapping_review(self):
        rc, s = self.go([], skip_review=ReviewSkipConfig(tests=["f.txt"]))
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
