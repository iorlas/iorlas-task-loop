"""An interrupted planner answer stays a draft until send-back validation passes."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest

from taskloop.app.plan.sendback import SendBack
from taskloop.app.run import engine
from taskloop.contracts.kinds import Kind


class DraftCheckpoint(EngineTest):
    def interrupt_validation(self, plan):
        stopped = engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        with mock.patch.object(SendBack, "find", side_effect=stopped):
            rc, script = self.run_engine({"plan": [plan]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in script.calls], ["planner"])
        ck = self.checkpoint()
        self.assertEqual((ck["step"], ck["planned"], ck["plan"]["summary"]), ("plan", 1, plan["summary"]))

    def test_a_crash_before_sendback_keeps_a_draft_and_resume_rejects_it_before_write(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["bd show t-1"])])
        self.interrupt_validation(bad)
        rc, script = self.run_engine({"plan": [bad]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in script.calls], ["planner"])
        self.assertEqual(script.calls[0][1], "ref-plan")
        self.assertIn("issue tracker", script.prompts[0])
        self.assertEqual(self.eng.result().kind, "fault_plan")
        self.assertEqual(self.eng.planned, 1)

    def test_a_valid_draft_is_revalidated_without_another_planner_call(self):
        self.interrupt_validation(PLAN)
        find = SendBack.find
        with mock.patch.object(SendBack, "find", autospec=True, side_effect=find) as validate:
            rc, script = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        validate.assert_called_once()
        self.assertEqual([c[0] for c in script.calls], ["worker", "reviewer"])
        self.assertEqual(self.eng.planned, 1)
