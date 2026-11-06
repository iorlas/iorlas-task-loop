"""delegate-gsy: `run ROLE --only-family F` keeps only the role's steps of those families, same order, with no fallback outside them."""

import copy

from delegate.contracts.routing import CallArgs
from delegate.domain.routing.tiers import TierPlan

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_review_order import CFG, T, lanes


class OnlyFamilyTest:
    def decide(self, *up, role="worker", **kw):
        return support.decide(role, copy.deepcopy(CFG), lanes(*up), {}, T, dict({"authored_by": None, "unattended": True}, **kw))


    def test_no_step_of_another_family_is_ever_planned(self):
        plan = TierPlan(support.env.typed_routing(copy.deepcopy(CFG)))
        role = plan.r.roles["worker"]
        tiers = plan.tiers(role, CallArgs(only_family=("openai",))) or []
        steps = [x for tier in tiers for x in tier]
        assert steps
        assert ({x.on for x in steps}) == {"openai"}
        both = [x for tier in plan.tiers(role, CallArgs(only_family=("xai", "openai"))) or [] for x in tier]
        assert ({x.on for x in both}) == {"xai", "openai"}
        assert [x.model for x in both if x.on == "openai"] == [x.model for x in steps]

    def test_when_the_family_is_not_ready_the_answer_is_a_stop_with_the_reason(self):
        d = self.decide("xai", "claude", only_family=["openai"])
        assert (d["action"], d["reason"]) == ("stop", "only_family_unready")
        assert "lane" not in d
        assert d.get("ask_user") is None
        assert "--only-family openai" in d["say"]
        assert "no other family is used" in d["say"]

    def test_a_family_with_no_step_in_the_role_is_a_stop_too(self):
        d = self.decide("openai", "xai", "claude", only_family=["nonesuch"])
        assert (d["action"], d["reason"]) == ("stop", "only_family_unready")
