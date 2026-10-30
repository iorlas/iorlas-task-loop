"""tl-9un.1: the acceptance probe. What the AC names that cannot work is a planner fact before the first plan; nothing copied from
bead text is run (SAFEACT): a registered check runs once on the base, any other command is only looked up."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import BEAD, CLEAN, PLAN, WRITE, EngineTest

# isort: split
from support import procsim
from support.logs import records

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


class AcProbeTest(EngineTest):
    def run_ac(self, ac, **cfg):
        with self.store.stub(show=dict(BEAD, acceptance_criteria=ac)):
            _, s = self.run_engine(ANSWERS, **cfg)
        return s.prompts[0], records(self.eng, "note")

    def test_a_missing_command_in_the_ac_is_a_fact_before_planning(self):
        prompt, notes = self.run_ac("- `nonesuch-tool --check` exits 0")
        self.assertIn("AC names `nonesuch-tool --check`, which does not exist here", prompt)
        self.assertTrue(any("`nonesuch-tool` not found" in n["text"] for n in notes))

    def test_a_command_that_is_not_registered_is_never_run(self):
        ran = Path(self.tmp.name) / "ran"
        cmd = procsim.fake("stray-tool go", procsim.appends(ran))
        prompt, _ = self.run_ac(f"- `{cmd}` exits 0")
        self.assertFalse(ran.exists())
        self.assertNotIn("does not exist here", prompt)  # the program is found: looked up, not run

    def test_a_registered_check_that_passes_on_the_base_is_already_true(self):
        ran = Path(self.tmp.name) / "ran"
        cmd = procsim.fake("green-check x", procsim.appends(ran))
        prompt, notes = self.run_ac("- `green-check x` passes", checks=[{"id": "gc", "cmd": cmd}])
        self.assertIn("`gc`, which is already true", prompt)
        self.assertEqual(ran.read_text()[:1], "1")
        self.assertTrue(any(n["text"].startswith("acceptance probe: `gc` passed") for n in notes))

    def test_a_registered_check_named_by_id_is_run_once_and_a_red_one_is_no_fact(self):
        cmd = procsim.fake("red-check", procsim.exits(1, "assert 1 == 2"))
        prompt, notes = self.run_ac("- `rc` is green", checks=[{"id": "rc", "cmd": cmd}])
        self.assertNotIn("already true", prompt)
        self.assertNotIn("cannot run on this host", prompt)
        self.assertTrue(any(n["text"].startswith("acceptance probe: `rc` failed") for n in notes))

    def test_a_check_this_host_cannot_run_is_a_fact_to_ask_about(self):
        cmd = procsim.fake("unity-check", procsim.exits(86, "no unity on this host"))
        prompt, _ = self.run_ac("- `unity-check` passes", checks=[{"id": "unity-check", "cmd": cmd}])
        self.assertIn("`unity-check`, which cannot run on this host", prompt)
        self.assertIn("ask the owner now", prompt)

    def test_the_probe_time_and_result_are_in_the_run_log(self):
        _, notes = self.run_ac("- `nonesuch-tool --check` exits 0")
        last = [n["text"] for n in notes if n["text"].startswith("acceptance probe:")][-1]
        self.assertRegex(last, r"1 command\(s\) named, 0 registered check\(s\) run, 1 fact\(s\) in \d+\.\d s")

    def test_stage_rounds_keep_their_numbers(self):
        cmd = procsim.fake("green-check x", procsim.exits(0))
        self.run_ac("- `green-check x` passes", checks=[{"id": "gc", "cmd": cmd}])
        self.assertEqual(self.eng.checker.round, 1)
