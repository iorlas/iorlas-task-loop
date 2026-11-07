"""Whole beads through the Engine, moved out of tests/checks/test_check_rerun.py (they run the pipeline, not only the checks stage)."""
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest
from support.plans import CLEAN, PLAN, WRITE

from tltestkit import procsim

REPO: list[dict[str, Any]] = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}]


class Planned(EngineTest):
    def test_the_refusal_reaches_the_planner_and_the_corrected_plan_runs(self):
        procsim.fake("just unity-tests", procsim.exits(0))
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests --filter X"])])
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, checks=REPO)
        assert [c[0] for c in s.calls][:2] == ["planner", "planner"]
        assert "runs the registered check `unity-tests`" in s.prompts[1]
        assert "TL_CHECK_LOG_UNITY_TESTS" in s.prompts[1]
