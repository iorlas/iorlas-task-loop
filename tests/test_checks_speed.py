"""Check rounds that cost less: per-check input cache, cheap-first order, duplicate runs, hang watchdog."""
import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402
from test_engine import PY, engine  # noqa: E402,F401
import checks_speed as cs  # noqa: E402


class SpeedTest(unittest.TestCase):
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd
    commit_base_cfg = te.EngineTest.commit_base_cfg
    run_engine = te.EngineTest.run_engine
    checks_engine = te.EngineTest.checks_engine

    def bump(self, name="count"):
        n = Path(self.tmp.name) / name
        return PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(n), n

    def notes(self, eng):
        return [json.loads(l).get("text", "") for l in eng.log_path.read_text().splitlines() if '"kind": "note"' in l]


class InputCache(SpeedTest):
    ST = {"checks": [], "files": []}

    def test_a_check_with_inputs_survives_edits_outside_them_and_a_moved_base(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "inputs": ["client/**"]}])
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        eng.run_checks(self.ST, "s")
        (self.wt / "README.md").write_text("doc\n")  # outside the inputs
        te.sh("git", "commit", "--allow-empty", "-qm", "x", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)  # the base moves
        again = eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "1")
        self.assertTrue(again[0]["cached"])
        self.assertTrue(any("cached: unity, inputs unchanged since round 1" in t for t in self.notes(eng)))

    def test_an_edit_inside_the_inputs_or_another_command_reruns(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "inputs": ["client/**"]}])
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        eng.run_checks(self.ST, "s")
        (self.wt / "client" / "a.cs").write_text("2\n")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")
        eng2 = self.checks_engine(checks=[{"id": "unity", "cmd": cmd + " ", "group": "tests", "inputs": ["client/**"]}])
        eng2.run_checks(self.ST, "s")  # same text after whitespace normalisation: still a hit
        self.assertEqual(n.read_text(), "11")
        eng3 = self.checks_engine(checks=[{"id": "unity", "cmd": cmd + " # other", "group": "tests", "inputs": ["client/**"]}])
        eng3.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "111")

    def test_without_inputs_any_untracked_file_still_throws_the_result_away(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "t", "cmd": cmd, "group": "tests"}])
        eng.run_checks(self.ST, "s")
        (self.wt / "README.md").write_text("doc\n")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")

    def test_a_red_check_with_inputs_is_not_remembered(self):
        eng = self.checks_engine(checks=[{"id": "t", "cmd": te.FALSE, "group": "tests", "inputs": ["*.txt"]}])
        eng.run_checks(self.ST, "s")
        self.assertFalse(eng.run_checks(self.ST, "s")[0].get("cached"))

    def test_inputs_hash_ignores_files_outside_the_globs(self):
        a = {"x/a": "100644 blob 1", "y/b": "100644 blob 2"}
        b = dict(a, **{"y/b": "100644 blob 3"})
        self.assertEqual(cs.inputs_hash(a, ["x/**"]), cs.inputs_hash(b, ["x/**"]))
        self.assertNotEqual(cs.inputs_hash(a, ["y/**"]), cs.inputs_hash(b, ["y/**"]))
        self.assertEqual(cs.inputs_hash(a, ["z/**"]), "")


class CheapFirst(SpeedTest):
    def slow_then_fast(self):
        mark = Path(self.tmp.name) / "order"
        step = lambda name: PY + ' -c "open(%r, \'a\').write(\'%s \')"' % (str(mark), name)
        return mark, step("slow"), step("quick")

    def seed(self, eng, cmd, secs):
        cs.record_durations(str(self.wt), [(cmd, secs)] * 3, config_dir=os.environ["XDG_CONFIG_HOME"] + "/task-loop")

    def test_the_cheaper_check_runs_first_and_a_red_stops_the_round(self):
        mark, slow, quick = self.slow_then_fast()
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": slow, "group": "tests"},
                                         {"id": "quick", "cmd": quick + "; exit 1", "group": "tests"}])
        self.seed(eng, slow, 400)
        self.seed(eng, quick + "; exit 1", 2)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c["id"] for c in res], ["quick", "slow"])
        self.assertEqual([c["status"] for c in res], ["failed", "skipped"])
        self.assertEqual(mark.read_text(), "quick ")

    def test_unknown_commands_count_as_cheap_and_durations_are_recorded(self):
        mark, slow, quick = self.slow_then_fast()
        eng = self.checks_engine(checks=[{"id": "known", "cmd": slow, "group": "tests"},
                                         {"id": "new", "cmd": quick, "group": "tests"}])
        self.seed(eng, slow, 90)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c["id"] for c in res], ["new", "known"])
        hist = cs.load_durations(str(self.wt))
        self.assertEqual(len(hist[cs.norm(quick)]), 1)
        self.assertEqual(len(hist[cs.norm(slow)]), 4)

    def test_a_check_reading_another_checks_log_stays_after_it(self):
        reader = 'test -n "$TL_CHECK_LOG_SLOW"'
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": PY + ' -c "pass"', "group": "tests"},
                                         {"id": "reader", "cmd": reader, "group": "tests"}])
        self.seed(eng, PY + ' -c "pass"', 300)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([(c["id"], c["status"]) for c in res], [("slow", "ran"), ("reader", "ran")])

    def test_order_ignores_sub_five_second_noise(self):
        items = [{"cmd": "a", "g": 0}, {"cmd": "b", "g": 0}]
        hist = {"a": [3.0], "b": [0.1]}
        self.assertEqual([i["cmd"] for i in cs.order_by_cost(items, hist, lambda c: 0)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
