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


if __name__ == "__main__":
    unittest.main()
