"""Plan behaviour on fake ports, without constructing an Engine."""
from dataclasses import replace
from pathlib import Path

import pytest
from support.cfgs import cfg_with
from support.checks import typed
from support.plan_host import FakePlan
from support.plans import HAS_F, PLAN

from taskloop.app.asks import intake
from taskloop.app.plan import adrsync
from taskloop.app.plan.planned import Planned
from taskloop.domain.prompts.common import RULES_MAX
from tlkernel import adrfiles
from tlkernel.bead import Bead
from tlkernel.ledger import Adr
from tlkernel.plancheck import adhoc
from tlkernel.stop import Stop


def test_outside_scope_is_filed_once_and_taste_stays(workdir):
    plan = FakePlan(workdir)
    plan.hand.scope = "Acceptance Criteria\n- the soak passes with three lifers across five seeds"
    plan.hand.plan_data = typed(PLAN)
    inside = {"what": "the soak holds with three lifers on seed 4", "kind": "checkable"}
    outside = {"what": "Sit To Stand and Laying Sleeping poses were not probed", "kind": "checkable"}
    taste = {"what": "Sit To Stand and Laying Sleeping poses look right", "kind": "taste"}
    assert plan.cases.out_of_scope([inside, outside, taste]) == [inside, taste]
    assert plan.cases.out_of_scope([outside]) == []
    assert len(plan.hand.leftovers) == 1
    assert "Sit To Stand" in plan.hand.leftovers[0]["title"]
    assert plan.ports.checkpoints.kept == ["pending:scope"]


def test_cases_without_commands_are_not_run(workdir):
    plan = FakePlan(workdir)
    plan.hand.plan_data = typed(dict(PLAN, cases=[
        {"criterion": "file exists", "check": HAS_F},
        {"criterion": "gate passes", "proved_by": "engine_step", "via": "land gate"},
        {"criterion": "import prefabs", "proved_by": "leftover", "via": "later"},
        {"criterion": "looks right", "class": "taste"},
    ]))
    assert plan.cases.case_checks() == [adhoc(HAS_F)]


def test_cap_override_grants_one_extra_run_once(workdir):
    plan = FakePlan(workdir)
    bead = plan.facts.bead
    plan.ports.store.beads[bead] = Bead(id=bead, title="task", status="open", metadata={intake.OVERRIDE: "replan-cap"})
    plan.cap.grant()
    plan.cap.grant()
    assert plan.plan_state.cap_granted
    assert plan.hand.extra == 1
    assert intake.OVERRIDE not in plan.ports.store.beads[bead].metadata


def test_cap_stops_before_counting_another_plan(workdir):
    plan = FakePlan(workdir, cfg_with(max_replans=0))
    plan.hand.planned = 1
    with pytest.raises(Stop, match=r"1 times .*1 plan \+ 0 amends"):
        plan.planner.count(None, True, "failed")
    assert plan.hand.planned == 1
    assert plan.hand.plan_log == []


def test_old_plan_prompt_uses_amend_text_before_the_replan_cause(workdir):
    plan = FakePlan(workdir)
    plan.amend.text = "the owner changed the acceptance"
    prompt = plan.planner.prompts.change(typed(PLAN), False, "failed")
    assert "<old_plan>" in prompt
    assert "smallest change" in prompt
    assert "<change>\nthe owner changed the acceptance\n</change>" in prompt
    assert plan.amend.text == "the owner changed the acceptance"


def test_leftovers_are_added_once_per_title_and_keeper_retains_identity(workdir):
    plan = FakePlan(workdir)
    data = typed(dict(PLAN, leftovers=[{"title": "later", "why": "outside this plan"}]))
    plan.planner.add_leftovers(data)
    plan.planner.add_leftovers(data)
    assert plan.hand.leftovers == data["leftovers"]
    p = Planned(plan_data=data, summary=data["summary"], planned=3)
    assert plan.planner.take(p) is data
    assert plan.planner.take(p) is data
    assert (plan.hand.plan_data, plan.hand.plan_summary, plan.hand.planned) == (data, p.summary, 3)


def test_only_known_citations_are_counted_once(workdir, monkeypatch):
    plan = FakePlan(workdir)
    adr = Adr(id="ADR-1", n=1, repo="repo", text="Saves stay in format v1.", question="q?", answer="a", ask="x-1",
              bead="x", key="", t=1.0)
    monkeypatch.setattr(adrsync, "files_at", lambda *a: {"docs/adr/0001-saves.md": adrfiles.render(adr)})
    assert plan.planner.decisions.cited(typed(dict(PLAN, cited=["ADR-1", "ADR-1", "ADR-77"]))) == ["ADR-1"]
    uses = plan.ports.stores.adrs("repo").uses()
    assert [(u.adr, u.bead) for u in uses] == [("ADR-1", "t-1")]


def test_worker_rules_are_clipped_at_a_line_and_missing_ones_say_nothing(workdir):
    plan = FakePlan(workdir, cfg_with(worker_rules="r.md"))
    wt = Path(plan.facts.wt)
    wt.mkdir()
    (wt / "r.md").write_text("line\n" * 1000)
    text = plan.cases.rules_text()
    assert len(text.encode("utf-8")) <= RULES_MAX
    assert text.endswith("line") and plan.ports.warned
    plan.cases.facts = replace(plan.facts, cfg=cfg_with(worker_rules="nope.md"))
    assert plan.cases.rules_text() == ""
    plan.cases.facts = replace(plan.facts, cfg=cfg_with(worker_rules=""))
    assert plan.cases.rules_text() == ""
