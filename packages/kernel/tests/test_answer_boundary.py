"""Optional irreversible actions must survive strict checkpoint decoding."""
import pytest

from tlkernel.answers import IRREVERSIBLE
from tlkernel.plancheck import PlanData, plan_of
from tlkernel.wire import builtins, load
from tltestkit.plans import PLAN


def test_planner_answer_null_irreversible():
    raw = dict(PLAN, irreversible=None)
    plan = plan_of(raw)
    assert plan["irreversible"] == ""
    restored = load(PlanData, builtins(plan))
    assert restored["irreversible"] == ""
    assert restored["irreversible"] not in IRREVERSIBLE
    assert raw["irreversible"] is None


@pytest.mark.parametrize("action", ["", "push_shared"])
def test_planner_answer_irreversible(action):
    raw = dict(PLAN, irreversible=action)
    plan = plan_of(raw)
    assert plan["irreversible"] == action
    restored = load(PlanData, builtins(plan))
    assert restored["irreversible"] == action
    assert (restored["irreversible"] in IRREVERSIBLE) == (action == "push_shared")
    assert raw["irreversible"] == action


def test_planner_answer_without_irreversible():
    raw = dict(PLAN)
    raw.pop("irreversible", None)
    plan = plan_of(raw)
    assert "irreversible" not in plan
    restored = load(PlanData, builtins(plan))
    assert "irreversible" not in restored
    assert "irreversible" not in raw
