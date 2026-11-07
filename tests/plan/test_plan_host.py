"""Engine and fake satisfy the plan capabilities and shared hand-offs."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing
from support.plan_host import FakePlan

from taskloop.app.plan.host import PlanHand, PlanPorts


class PlanHostConformance(EngineTest):
    def test_the_engine_has_every_member_the_plan_stage_reads(self):
        eng = make_engine(self.wt, store=self.store)
        assert missing(eng, PlanPorts) == []
        assert missing(eng, PlanHand) == []

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.checker
        assert missing(eng, PlanPorts) == ["checker"]


def test_fake_has_every_plan_capability_and_hand_field(workdir):
    plan = FakePlan(workdir)
    assert missing(plan.ports, PlanPorts) == []
    assert missing(plan.hand, PlanHand) == []
