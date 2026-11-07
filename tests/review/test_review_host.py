"""The Engine satisfies ReviewHand: every member the review stage names is on the engine a run builds."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing
from support.review_host import FakeReview

from tlwork.review.host import ReviewHand, ReviewPorts


class ReviewHandConformance(EngineTest):
    def test_the_engine_has_every_member_the_review_stage_reads(self):
        eng = make_engine(self.wt, store=self.store)
        assert (missing(eng, ReviewHand), missing(eng, ReviewPorts)) == ([], [])

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.steps
        assert missing(eng, ReviewPorts) == ["steps"]


def test_the_fake_review_has_every_member_the_stage_reads(workdir):
    review = FakeReview(workdir)
    assert (missing(review.hand, ReviewHand), missing(review.ports, ReviewPorts)) == ([], [])

def test_the_fake_review_sink_writes_its_hand_off_list(workdir):
    review = FakeReview(workdir)
    lo = {"title": "later"}
    assert review.ports.leftover_sink.add_titled(lo)
    assert review.hand.leftovers == [lo]
