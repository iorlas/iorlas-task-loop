"""Engine tests: the gate as a registry of checks. A check says `run`: stage (the round after each write), gate (a step of land's gate) or
both; the gate runs its steps through the checks' own machinery and cache."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest, pyc

# isort: split
from support.logs import records

from taskloop.domain.checks.specs import gate_items, items_of

STEP = pyc("pass")
RED_ON_D2 = pyc("import sys; t=open('f.txt').read().strip(); print('step saw', t); sys.exit(1 if t == 'd2' else 0)")
ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


def ends(eng, name):
    """{check name: its CheckEnd record} of the check log (the starts name them)."""
    names = {r["id"]: r["check"] for r in records(eng, "check_start")}
    return {names[r["id"]]: r for r in records(eng, "check_end")}


class GateSteps(EngineTest):
    def test_a_check_with_run_stage_is_not_in_the_gate(self):
        eng = self.checks_engine(checks=[{"id": "s", "cmd": STEP}, {"id": "g", "cmd": STEP, "run": "gate"},
                                         {"id": "b", "cmd": STEP, "run": "both"}])
        self.assertEqual([c.id for c in gate_items(eng.cfg)], ["g", "b"])
        self.assertEqual([c.id for c in items_of(eng.cfg, [])], ["s", "b"])  # and a gate-only step is no stage check

    def test_each_gate_step_has_its_own_seconds_and_exit_in_the_check_log(self):
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "one", "cmd": STEP, "run": "gate", "group": "static"},
                                                 {"id": "two", "cmd": STEP, "run": "gate"}])
        self.assertEqual(rc, 0, self.blocked)
        for step in ("one", "two"):
            done = ends(self.eng, step)[step]
            self.assertEqual((done["exit"], done["status"]), (0, "passed"))
            self.assertIn("secs", done)
        self.assertEqual(len(records(self.eng, "gate_start")), 1)

    def test_a_red_gate_names_the_step_and_hands_its_output_to_the_fix_round(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                                checks=[{"id": "fmt", "cmd": STEP, "run": "gate", "group": "static"},
                                        {"id": "unit", "cmd": RED_ON_D2, "run": "gate"}])
        self.assertEqual(rc, 0, self.blocked)
        fix = s.prompts[3]
        self.assertIn("gate steps red: unit", fix)
        self.assertIn("step saw d2", fix)
        self.assertNotIn("gate steps red: fmt", fix)
        self.assertEqual(ends(self.eng, "fmt")["fmt"]["status"], "passed")

    def test_a_step_green_at_its_inputs_is_skipped_and_logged_as_cached(self):
        count = Path(self.tmp.name) / "runs"
        both = pyc(f"open({str(count)!r}, 'a').write('1')")
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "ut", "cmd": both, "run": "both", "inputs": ["f.txt"]}])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "1")  # the stage round ran it; the gate on the same inputs did not
        self.assertEqual(ends(self.eng, "ut")["ut"]["status"], "cached")
        gate_end = records(self.eng, "gate_end")[-1]
        self.assertTrue(gate_end["skipped"])

    def test_a_gate_with_no_steps_is_no_gate(self):
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "s", "cmd": STEP}])
        self.assertEqual((rc, records(self.eng, "gate_start")), (0, []))
