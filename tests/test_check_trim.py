"""tl-7y6.7.17: a check's output is trimmed before any agent prompt carries it."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
sys.path.insert(0, str(ROOT / "tests"))
import engine  # noqa: E402
import test_engine as te  # noqa: E402
from checks import trim  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "checklogs"

# fixture -> lines that must survive: every failing test name, and its first assertion / compile error line
MUST = {
    "unittest_fail.log": ["FAIL: test_refund_rounds", "AssertionError: Decimal('10.04') != Decimal('10.05')",
                          "ERROR: test_total_tax", "KeyError: 'XX'", "FAILED (failures=1, errors=1)"],
    "pytest_fail.log": ["test_evicts_oldest_entry", "E       assert 1 is None", "test_ttl_expires_with_clock",
                        "E       AssertionError: assert 'k' not in", "2 failed, 116 passed"],
    "nunit_fail.log": ["Failed  Game.Tests.Combat.DamageTests.CritDoublesDamage", "Expected: 40",
                       "Failed  Game.Tests.Save.RoundTripTests.LoadsLegacySlot", "System.NullReferenceException",
                       "Failed: 2, Passed: 29"],
    "compile_error.log": ["Weapon.cs(52,17): error CS1002", "Weapon.cs(60,9): error CS0103", "Hud.cs(14,22): error CS0246"],
    "shell_exit_only.log": ["missing file: /work/.env.local"],
    "pytest_many_fail.log": ["test_scenario_00", "assert 0 == 1", "test_scenario_13", "assert 13 == 14", "14 failed, 386 passed"],
}
LOGPATH = "/runs/r1/checks/00-check.r1.log"


class TrimFixtures(unittest.TestCase):
    def test_every_failing_name_and_first_assertion_survives_within_the_cap(self):
        for name, must in MUST.items():
            with self.subTest(log=name):
                text = (FIX / name).read_text()
                out = trim.trim_log(text, log=LOGPATH)
                self.assertLessEqual(len(out.encode()), trim.CAP, name)
                self.assertIn(LOGPATH, out)  # the full log is one path away
                for line in must:
                    self.assertIn(line, out, "%s lost: %s" % (name, line))

    def test_too_many_failures_for_the_cap_keep_the_first_ones_and_say_what_was_left_out(self):
        text = "\n".join("FAILED tests/t.py::test_case_%03d - assert %d == 0" % (i, i) for i in range(300))
        out = trim.trim_log(text, log=LOGPATH)
        self.assertLessEqual(len(out.encode()), trim.CAP)
        self.assertIn("more failing lines left out", out)
        self.assertIn("test_case_000", out)  # the first failures come first

    def test_the_tail_is_kept_and_noise_in_the_middle_is_not(self):
        text = "\n".join(["boring line %d" % i for i in range(500)] + ["FAILED test_x - assert 1 == 2"] +
                         ["tail line %d" % i for i in range(60)])
        out = trim.trim_log(text, log=LOGPATH)
        self.assertIn("tail line 59", out)
        self.assertIn("FAILED test_x", out)
        self.assertNotIn("boring line 250", out)
        self.assertLessEqual(len(out.encode()), trim.CAP)

    def test_a_giant_line_and_a_small_cap_still_fit(self):
        text = "FAIL: test_a\n" + "x" * 100000 + "\nAssertionError: boom\n" + "\n".join("l%d" % i for i in range(300))
        out = trim.trim_log(text, log=LOGPATH, cap=1024)
        self.assertLessEqual(len(out.encode()), 1024)
        self.assertIn("FAIL: test_a", out)
        self.assertIn("AssertionError: boom", out)

    def test_zero_errors_is_no_failure_line(self):
        text = "\n".join(["    0 Error(s)", "Failed: 0"] * 5 + ["line %d" % i for i in range(100)] + ["done"])
        out = trim.trim_log(text, cap=600)
        self.assertNotIn("0 Error(s)", out)

    def test_a_green_check_is_one_line_with_no_log(self):
        green = trim.green_line("just check", 12.4)
        self.assertEqual(green.count("\n"), 0)
        self.assertEqual(green, "`just check` passed in 12 s")
        text = (FIX / "long_green.log").read_text()
        self.assertNotIn("PASS tests", green + text[:0])


class BriefPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)
        (self.run_dir / "checks").mkdir()
        for f in FIX.glob("*.log"):
            (self.run_dir / "checks" / f.name).write_text(f.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def test_failure_brief_trims_every_red_fixture_and_names_the_log(self):
        for name, must in MUST.items():
            with self.subTest(log=name):
                out = engine.failure_brief([dict(cmd="c", exit=1, log="checks/" + name)], self.run_dir)
                self.assertLessEqual(len(out.encode()), trim.CAP)
                self.assertIn(str(self.run_dir / "checks" / name), out)
                for line in must:
                    self.assertIn(line, out)

    def test_compact_red_keeps_the_failing_name_and_green_stays_one_line(self):
        tail = (FIX / "unittest_fail.log").read_text()[-1500:]
        red = engine.compact([dict(cmd="t", exit=1, status="failed", group="tests", tail=tail)])
        self.assertEqual(red.count("\n"), 0)
        self.assertLessEqual(len(red), 700)
        self.assertIn("FAIL: test_refund_rounds", red)
        green = engine.compact([dict(cmd="t", exit=0, status="ran", group="tests", tail=(FIX / "long_green.log").read_text()[-1500:])])
        self.assertEqual(green.count("\n"), 0)

    def test_the_stored_log_is_not_changed(self):
        before = (self.run_dir / "checks" / "nunit_fail.log").read_text()
        engine.failure_brief([dict(cmd="c", exit=1, log="checks/nunit_fail.log")], self.run_dir)
        self.assertEqual((self.run_dir / "checks" / "nunit_fail.log").read_text(), before)


class RedCheckPrompt(te.EngineTest.__mro__[1]):
    """The writer's prompt after a red check carries the trimmed form, not the log."""
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    commit_base_cfg = te.EngineTest.commit_base_cfg
    fake_bd = te.EngineTest.fake_bd
    run_engine = te.EngineTest.run_engine

    def test_the_second_write_sees_failure_lines_and_the_log_path_not_the_whole_log(self):
        script = Path(self.tmp.name, "noisy_check.py")
        script.write_text(
            "import sys\n"
            "for i in range(600): print('setup step %d ok, nothing to see here' % i)\n"
            "print('FAIL: test_refund_rounds (tests.test_orders.OrderTests)')\n"
            "print('AssertionError: 10.04 != 10.05')\n"
            "for i in range(80): print('teardown %d' % i)\n"
            "sys.exit(0 if open('f.txt').read().strip() == 'd3' else 1)\n")
        check = te.PY + ' "%s"' % script
        plan = dict(te.PLAN, stages=[dict(te.PLAN["stages"][0], checks=[check])])
        rc, s = self.run_engine({"plan": [plan], "write": [te.WRITE, te.WRITE], "review": [te.CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        writes = [p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual(len(writes), 2)
        second = writes[1]
        self.assertIn("These checks fail", second)
        self.assertIn("FAIL: test_refund_rounds", second)
        self.assertIn("AssertionError: 10.04 != 10.05", second)
        self.assertIn(".log", second)  # the path of the full log
        self.assertNotIn("setup step 300 ok", second)
        self.assertNotIn("setup step 598 ok", second)  # only the line before the failure comes with it
        self.assertLess(len(second) - len(writes[0]), 2 * trim.CAP)
        self.assertNotIn("setup step", writes[0])  # the first write has no check output at all


if __name__ == "__main__":
    unittest.main()
