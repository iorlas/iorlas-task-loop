"""Planner effects stay visible before collaborators read the plan."""
import ast
from contextlib import ExitStack
from pathlib import Path

import pytest
from support.engine_case import EngineTest

from tltestkit.checks import typed
from tltestkit.plans import CLEAN, PLAN, WRITE
from tlwork.plan import planner
from tlwork.plan.planned import Planned


@pytest.fixture
def world():
    case = EngineTest()
    with ExitStack() as stack:
        case._testMethodName = "setup_method"
        case.addCleanup = stack.callback
        case.setup_method()
        try:
            yield case
        finally:
            case.teardown_method()


def test_ledger_reads_the_accepted_plan_before_the_pipeline_stores_it(world):
    seen = []
    returned = []

    def prep(e):
        plan, ledger = e.planner.plan, e.routing.ledger

        def planning(*a, **kw):
            def reading():
                seen.append(e.plan_data)
                return ledger()

            save, summary = e.checkpoints.save, e.plan_summary
            checkpoints = []

            def saving(**kw):
                checkpoints.append((kw["step"], e.plan_data, e.plan_summary))
                return save(**kw)

            e.routing.ledger = reading
            e.checkpoints.save = saving
            try:
                result = plan(*a, **kw)
                assert e.plan_data is result.plan_data
                assert result.summary == result.plan_data["summary"]
                assert result.planned == e.planned
                assert [step for step, _, _ in checkpoints] == ["plan", "write", "write"]
                assert checkpoints[0][1]["summary"] == result.summary
                assert checkpoints[0][1] is not result.plan_data
                assert checkpoints[1][1] is result.plan_data
                assert [text for _, _, text in checkpoints] == [summary, summary, result.summary]
                returned.append(result)
                return result
            finally:
                e.routing.ledger = ledger
                e.checkpoints.save = save

        e.planner.plan = planning

    rc, _ = world.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
    assert rc == 0
    assert len(returned) == 1
    assert seen
    assert all(data is returned[0].plan_data for data in seen)


def test_planner_assigns_only_stage_owned_state():
    tree = ast.parse(Path(planner.__file__).read_text())
    forbidden = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Store):
            continue
        parts = []
        base = node
        while isinstance(base, ast.Attribute):
            parts.insert(0, base.attr)
            base = base.value
        if not isinstance(base, ast.Name):
            continue
        if base.id == "self" and len(parts) > 1 and parts[:1] == ["host"]:
            parts = parts[1:]
        elif base.id not in {"e", "host"}:
            continue
        if len(parts) < 2 or parts[0] not in {"amend", "plan_state", "review"}:
            forbidden.append((node.lineno, ast.unparse(node)))
    assert forbidden == []


def test_take_planned_is_idempotent_and_keeps_identity(world):
    e = world.checks_engine()
    data = typed(PLAN)
    p = Planned(plan_data=data, summary=data["summary"], planned=3)
    assert e.planner.take(p) is data
    assert e.planner.take(p) is data
    assert (e.plan_data, e.plan_summary, e.planned) == (data, p.summary, 3)
    leftovers = e.leftovers
    e.planner.keep.leftovers([{"title": "later", "why": "outside this plan"}])
    assert e.leftovers is leftovers
    assert leftovers[-1]["title"] == "later"
