"""Whole beads through the Engine, moved out of tests/checks/test_runkey.py (they run the pipeline, not only the checks stage)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest

from tltestkit import procsim
from tltestkit.logs import records
from tltestkit.plans import CLEAN, PLAN, WRITE

# isort: split


ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
ST = {"checks": [], "files": []}



class Gate(EngineTest):
    def stage_then_gate(self, **extra):
        n = Path(self.tmp.name) / "runs"
        both = procsim.fake("both", procsim.appends(n))
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "ut", "cmd": both, "run": "both", **extra}])
        assert rc == 0, self.blocked
        assert n.read_text() == "11"  # the stage's slot pass cannot replace the clean gate's evidence
        assert not records(self.eng, "gate_end")[-1]["skipped"]
    def test_gate_green_is_every_key_in_the_memo(self):
        n = Path(self.tmp.name) / "runs"
        eng = self.checks_engine(checks=[{"id": "g", "cmd": procsim.fake("g", procsim.appends(n)), "run": "both"}])
        assert not eng.checker.gate_green()
        eng.run_checks(ST, "s")
        assert eng.checker.gate_green()
        (self.wt / "new.txt").write_text("x")  # another tree: another key
        assert not eng.checker.gate_green()

    def test_the_land_gate_reruns_a_whole_tree_check_a_stage_ran_green(self):
        self.stage_then_gate()

    def test_the_land_gate_reruns_a_check_with_inputs_a_stage_ran_green(self):
        self.stage_then_gate(inputs=["f.txt"])

    def test_the_land_gate_reruns_a_check_with_an_env_a_stage_ran_green(self):
        self.stage_then_gate(env={"A": "1"})
