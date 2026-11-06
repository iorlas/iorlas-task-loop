"""The Engine satisfies LookHost: every member the look stage names is on the engine a run builds."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing

from taskloop.app.look.host import LookHost


class LookHostConformance(EngineTest):
    def test_the_engine_has_every_member_the_look_stage_reads(self):
        assert missing(make_engine(self.wt, store=self.store), LookHost) == []

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.look_retried
        assert missing(eng, LookHost) == ["look_retried"]
