"""The replan prompt carries the tree's diff stat and a budget for looking, and only on a replan."""

import pytest
from tlkernel.ids import TreeSha
from tltestkit.checks import typed
from tltestkit.plans import PLAN

from tlwork.plan.prompt import REPLAN_CALLS
from tlwork.testing import FakePlan


@pytest.fixture
def plan(workdir):
    plan = FakePlan(workdir)
    plan.ports.checkout.tree = TreeSha("abc")
    plan.ports.hand.value = "- stage 1, round 1 (review); sent back: x\n"
    plan.ports.git.replies[("diff",)] = " a.py | 2 +-\n"
    return plan


def test_a_replan_gets_the_diff_stat_and_the_budget(plan):
    text = plan.planner.prompts.history(typed(PLAN), False)
    assert "<tree>\na.py | 2 +-\n</tree>" in text
    assert f"at most {REPLAN_CALLS} files" in text
    assert "sent back: x" in text


def test_a_first_plan_gets_neither(plan):
    assert plan.planner.prompts.history(None, False) == ""


def test_no_tree_says_nothing_changed(plan):
    plan.ports.checkout.tree_hash = lambda: ""
    assert "(no file changed yet)" in plan.planner.prompts.history(None, True)
