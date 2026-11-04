"""Engine tests: the gate as a registry of checks. A check says `run`: stage (the round after each write), gate (a step of land's gate) or
both; the gate runs its steps through the checks' own machinery and cache."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest

# isort: split
from support.logs import records

from taskloop.contracts.checks import Check
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.specs import due, engine_digest, gate_items, items_of

STEP = "true"
RED_ON_D2 = procsim.default("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, f"step saw {procsim.f_txt(cwd)}"))
ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


def ends(eng, name):
    """{check name: its CheckEnd record} of the check log (the starts name them)."""
    names = {r["id"]: r["check"] for r in records(eng, "check_start")}
    return {names[r["id"]]: r for r in records(eng, "check_end")}


class GateSteps(EngineTest):
    def test_check_run_carries_the_identity_from_before_execution(self):
        def change_files(cwd, env):
            (Path(cwd) / "f.txt").write_text("changed by gate")
            return 0, ""

        cmd = procsim.fake("change-files", change_files)
        eng = self.checks_engine(checks=[{"id": "mutator", "cmd": cmd, "run": "gate"}])
        tree = eng.checkout.tree_hash()
        base = eng.git.rev_parse(str(eng.wt), eng.cfg.base)
        config = engine_digest(eng.cfg)
        run = eng.checker.run_items(gate_items(eng.cfg))
        assert (run.tree, run.base, run.config) == (tree, base, config)
        assert eng.checkout.tree_hash() != tree

    def test_a_check_with_run_stage_is_not_in_the_gate(self):
        eng = self.checks_engine(checks=[{"id": "s", "cmd": STEP}, {"id": "g", "cmd": STEP, "run": "gate"},
                                         {"id": "b", "cmd": STEP, "run": "both"}])
        assert [c.id for c in gate_items(eng.cfg)] == ["g", "b"]
        assert [c.id for c in items_of(eng.cfg, [])] == ["s", "b"]  # and a gate-only step is no stage check

    def test_each_gate_step_has_its_own_seconds_and_exit_in_the_check_log(self):
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "one", "cmd": STEP, "run": "gate", "group": "static"},
                                                 {"id": "two", "cmd": STEP, "run": "gate"}])
        assert rc == 0, self.blocked
        for step in ("one", "two"):
            done = ends(self.eng, step)[step]
            assert (done["exit"], done["status"]) == (0, "passed")
            assert "exec_seconds" in done
        assert len(records(self.eng, "gate_start")) == 1

    def test_a_red_gate_names_the_step_and_hands_its_output_to_the_fix_round(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                                checks=[{"id": "fmt", "cmd": STEP, "run": "gate", "group": "static"},
                                        {"id": "unit", "cmd": RED_ON_D2, "run": "gate"}])
        assert rc == 0, self.blocked
        fix = s.prompts[3]
        assert "gate steps red: unit" in fix
        assert "step saw d2" in fix
        assert "gate steps red: fmt" not in fix
        assert ends(self.eng, "fmt")["fmt"]["status"] == "passed"

    def test_a_stage_pass_does_not_replace_a_clean_gate_run(self):
        count = Path(self.tmp.name) / "runs"
        both = procsim.fake("both", procsim.appends(count))
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "ut", "cmd": both, "run": "both", "inputs": ["f.txt"]}])
        assert rc == 0, self.blocked
        assert count.read_text() == "11"  # the slot and clean gate have different filesystem inputs
        assert ends(self.eng, "ut")["ut"]["status"] == "passed"
        gate_end = records(self.eng, "gate_end")[-1]
        assert not gate_end["skipped"]

    def test_a_gate_with_no_steps_is_no_gate(self):
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "s", "cmd": STEP}])
        assert (rc, records(self.eng, "gate_start")) == (0, [])


class When(EngineTest):
    def test_when_uses_the_inputs_glob_dialect_star_stays_in_one_folder(self):
        c = Check(id=CheckId("w"), cmd="true", when=["client/*.cs", "src/**", "{a,b}/x"])
        assert due(c, ["client/A.cs"])
        assert not due(c, ["client/deep/A.cs"])  # fnmatch's * crossed folders: the same glob said two things
        assert due(c, ["src/a/b/c.py"])
        assert due(c, ["b/x"])
        assert not due(c, ["docs/x"])
        assert due(Check(id=CheckId("n"), cmd="true"), [])
