"""Gate-only commands are named up front and left to land if the planner's rewrite keeps them."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.cfgs import cfg_with
from support.engine_case import EngineTest
from support.plan_host import FakePlan
from support.plans import CLEAN, HAS_F, PLAN, WRITE

from taskloop.app.plan.planner import Planner
from taskloop.domain.checks import lint
from tlkernel.plancheck import adhoc
from tltestkit.checks import typed


class GateOnly(EngineTest):
    def test_the_brief_names_every_gate_command_including_default_reasons(self):
        rc, script = self.run_engine(
            {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
            checks=[{"id": "layers", "cmd": "echo client-layers", "run": "gate"},
                    {"id": "suite", "cmd": "echo suite", "run": "gate", "why": "needs the rebased tree"}],
        )
        assert rc == 0
        brief = script.prompts[0]
        assert "`echo client-layers`" in brief
        assert "`echo suite` (needs the rebased tree)" in brief

    def test_a_single_gate_command_is_named_once(self):
        rc, script = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate="echo gate")
        assert rc == 0
        assert "These run only in the gate at land too" not in script.prompts[0]
        assert "never put `echo gate` in a stage's checks" in script.prompts[0]

    def test_a_gate_check_left_after_rewrite_is_dropped_and_the_run_continues(self):
        self.assert_gate_drop([HAS_F])

    def test_dropping_the_last_check_keeps_the_stage_and_the_run_continues(self):
        self.assert_gate_drop([])

    def assert_gate_drop(self, keep):
        command = "env CI=1 echo client-layers"
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[*keep, command])])
        rc, script = self.run_engine(
            {"plan": [bad, bad], "write": [WRITE], "review": [CLEAN]}, gate_only=["echo client-layers"],
        )
        assert rc == 0, self.blocked
        assert [c[0] for c in script.calls] == ["planner", "planner", "worker", "reviewer"]
        plan = self.eng.plan_data
        assert plan is not None
        stages = plan["stages"]
        assert len(stages) == 1
        assert stages[0]["checks"] == [adhoc(c) for c in keep]
        note = f"Plan check `{command}` left to the gate"
        assert note in self.eng.log_path.read_text()
        assert note in Planner.summary(plan)
        assert note in (self.eng.run_dir / "plan.json").read_text()
        assert any(note in c[3] for c in self.bd_calls if c[:2] == ("comments", "add"))

    def test_gate_checks_in_risks_and_cases_are_left_to_land_too(self, workdir):
        plan = FakePlan(workdir, cfg_with(gate_only=["echo gate"]))
        data = typed(dict(PLAN, risks=[{"what": "risk", "check": "echo gate"}],
                          cases=[{"criterion": "f.txt exists", "check": "echo gate"}]))
        with (mock.patch.object(lint, "dry_check", return_value=[]),
              mock.patch.object(plan.ports.log, "note") as note):
            plan.planner.sendback.after_rewrite(data)
            note.assert_called_once()
        assert data["risks"][0]["check"] is None
        assert data["cases"][0]["check"] is None
        assert data["cases"][0]["proved_by"] == "engine_step"
        assert data["cases"][0]["via"] == "land gate"
        assert lint.gate_only_checks(data, plan.facts.cfg) == []
        assert lint.ledger_problems(data) == []
        assert len(data["assumptions"]) == 1
