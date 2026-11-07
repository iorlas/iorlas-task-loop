"""An interrupted planner answer stays a draft until send-back validation passes."""
from unittest import mock

from support.engine_case import EngineTest

from taskloop.app.plan.sendback import SendBack
from taskloop.app.run import engine
from tlkernel.kinds import Kind
from tltestkit.plans import CLEAN, PLAN, WRITE


class DraftCheckpoint(EngineTest):
    def interrupt_validation(self, plan):
        stopped = engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        with mock.patch.object(SendBack, "find", side_effect=stopped):
            rc, script = self.run_engine({"plan": [plan]})
        assert rc == 2
        assert [c[0] for c in script.calls] == ["planner"]
        ck = self.checkpoint()
        assert (ck["step"], ck["planned"], ck["plan"]["summary"]) == ("plan", 1, plan["summary"])

    def test_a_crash_before_sendback_keeps_a_draft_and_resume_rejects_it_before_write(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["bd show t-1"])])
        self.interrupt_validation(bad)
        rc, script = self.run_engine({"plan": [bad]})
        assert rc == 2
        assert [c[0] for c in script.calls] == ["planner"]
        assert script.requests[0].thread == "planner"
        assert script.requests[0].delta_file
        assert "issue tracker" in script.prompts[0]
        assert self.eng.result().kind == "fault_plan"
        assert self.eng.planned == 1

    def test_a_valid_draft_is_revalidated_without_another_planner_call(self):
        self.interrupt_validation(PLAN)
        find = SendBack.find
        with mock.patch.object(SendBack, "find", autospec=True, side_effect=find) as validate:
            rc, script = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        validate.assert_called_once()
        assert [c[0] for c in script.calls] == ["worker", "reviewer"]
        assert self.eng.planned == 1
