"""The Engine satisfies ReviewHost: every member the review stage names is on the engine a run builds."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing

from taskloop.app.review.host import ReviewHost


class ReviewHostConformance(EngineTest):
    def test_the_engine_has_every_member_the_review_stage_reads(self):
        assert missing(make_engine(self.wt, store=self.store), ReviewHost) == []

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.review
        assert missing(eng, ReviewHost) == ["review"]
