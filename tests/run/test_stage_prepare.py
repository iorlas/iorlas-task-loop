"""Standalone write and check steps honor the coordinator's prerequisite retry without charging a write."""
from unittest import mock

from support.builders import plan_of
from support.engine_case import PLAN, EngineTest

from taskloop.app.run.stage_rounds import run_round_step
from taskloop.app.write.prepare import PREPARED, Prepare
from taskloop.app.write.state import StageState
from taskloop.contracts.enums import Step
from taskloop.contracts.procport import Ran


class StagePrepare(EngineTest):
    def test_write_step_prepares_and_retries_at_the_same_attempt(self):
        eng = self.checks_engine(prepare={"cmd": ["restore"], "triggers": ["restore"]})
        state = StageState(plan_of(PLAN), 0, None)

        def write(s, *, look):
            return PREPARED if Prepare(eng).retry(s, "restore") else ""

        with mock.patch.object(eng.spawner, "run", return_value=Ran(exit=0)) as run, \
                mock.patch.object(eng.stage_loop.writing, "run", side_effect=write) as writer:
            assert run_round_step(eng, Step.WRITE, state) == (Step.LOOK, False)
        assert (run.call_count, writer.call_count) == (2, 2)
        assert (state.n, eng.stats["writes"], eng.replans) == (1, 1, 0)

    def test_check_step_repairs_and_repeats_write_without_incrementing_attempt(self):
        eng = self.checks_engine(prepare={"cmd": ["restore"], "triggers": ["project.assets.json"]})
        state = StageState(plan_of(PLAN), 0, None)
        state.n = 1

        def check(s):
            return PREPARED if Prepare(eng).retry(s, "project.assets.json") else ""

        with mock.patch.object(eng.spawner, "run", return_value=Ran(exit=0)) as run, \
                mock.patch.object(eng.stage_loop.checking, "run", side_effect=check), \
                mock.patch.object(eng.stage_loop.writing, "run", return_value="") as writer:
            assert run_round_step(eng, Step.CHECKS, state) == (Step.LOOK, False)
        run.assert_called_once()
        writer.assert_called_once_with(state, look=False)
        assert (state.n, eng.stats["writes"], eng.replans) == (1, 0, 0)
