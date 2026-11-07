"""An untouched empty plan parks; existing work keeps the finished-work policy."""
import pytest
from support.checks import typed
from support.plan_host import FakePlan
from support.plans import PLAN

from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.contracts.kinds import Kind


@pytest.fixture
def plan(workdir):
    plan = FakePlan(workdir)
    plan.ports.blocked_for = blocked_for
    return plan


@pytest.mark.parametrize("leftovers", [[], [{"title": "Follow up", "why": "later"}]])
@pytest.mark.parametrize("again", [False, True])
def test_noop_with_or_without_followups_and_on_replan(plan, leftovers, again):
    data = typed(dict(PLAN, stages=[], leftovers=leftovers, summary="x" * 250))
    with pytest.raises(Blocked) as caught:
        plan.planner.finished_work(data, again)
    assert caught.value.kind == Kind.NOOP
    assert caught.value.why == "noop: the plan found nothing to implement: " + "x" * 200
    assert plan.hand.leftovers == leftovers
    assert plan.ports.published == 1


@pytest.mark.parametrize("diff", ["", "patch"])
def test_accepted_work_keeps_finished_work_behavior(plan, diff):
    plan.hand.done = ["accepted"]
    plan.ports.checkout.task_diff = lambda: diff
    data = typed(dict(PLAN, stages=[], leftovers=[{"title": "Follow up", "why": "later"}]))
    assert plan.planner.finished_work(data, False) is data
    assert plan.hand.leftovers == data["leftovers"]


@pytest.mark.parametrize("diff,landed", [("patch", ""), ("", "abc")])
def test_existing_diff_or_land_never_becomes_noop(plan, diff, landed):
    plan.hand.landed_sha = landed
    plan.ports.checkout.task_diff = lambda: diff
    with pytest.raises(Blocked) as caught:
        plan.planner.finished_work(typed(dict(PLAN, stages=[])), False)
    assert caught.value.kind == Kind.FAULT_PLAN


def test_verify_answer_without_work_also_becomes_noop(plan):
    plan.hand.verify_answer = "the work is right"
    with pytest.raises(Blocked) as caught:
        plan.planner.accept(typed(dict(PLAN, stages=[])), False)
    assert caught.value.kind == Kind.NOOP
