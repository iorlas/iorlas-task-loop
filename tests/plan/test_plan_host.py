"""The Engine satisfies PlanHost: every member the plan stage names is on the engine a run builds."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing

from taskloop.app.plan.host import PlanHost


class PlanHostConformance(EngineTest):
    def test_the_engine_has_every_member_the_plan_stage_reads(self):
        assert missing(make_engine(self.wt, store=self.store), PlanHost) == []

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.checker
        assert missing(eng, PlanHost) == ["checker"]
