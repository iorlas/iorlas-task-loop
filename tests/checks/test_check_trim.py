"""tl-7y6.7.17: a check's output is trimmed before any agent prompt carries it."""
import re
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

sys.path.insert(0, str(ROOT / "tests"))
from support.checks import res  # noqa: E402

from taskloop.app.checks import evidence  # noqa: E402
from taskloop.domain.checks import trim  # noqa: E402

FIX = Path(__file__).parents[1] / "fixtures" / "checklogs"

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


class TrimFixtures(Case):
    def test_every_failing_name_and_first_assertion_survives_within_the_cap(self):
        for name, must in MUST.items():
            with self.subTest(log=name):
                text = (FIX / name).read_text()
                out = trim.trim_log(text, log=LOGPATH)
                assert len(out.encode()) <= trim.CAP, name
                assert LOGPATH in out  # the full log is one path away
                for line in must:
                    assert line in out, f"{name} lost: {line}"

    def test_too_many_failures_for_the_cap_keep_the_first_ones_and_say_what_was_left_out(self):
        text = "\n".join(f"FAILED tests/t.py::test_case_{int(i):03d} - assert {i} == 0" for i in range(300))
        out = trim.trim_log(text, log=LOGPATH)
        assert len(out.encode()) <= trim.CAP
        assert "more failing lines left out" in out
        assert "test_case_000" in out  # the first failures come first

    def test_the_tail_is_kept_and_noise_in_the_middle_is_not(self):
        text = "\n".join([f"boring line {i}" for i in range(500)] + ["FAILED test_x - assert 1 == 2"] +
                         [f"tail line {i}" for i in range(60)])
        out = trim.trim_log(text, log=LOGPATH)
        assert "tail line 59" in out
        assert "FAILED test_x" in out
        assert "boring line 250" not in out
        assert len(out.encode()) <= trim.CAP

    def test_a_giant_line_and_a_small_cap_still_fit(self):
        text = "FAIL: test_a\n" + "x" * 100000 + "\nAssertionError: boom\n" + "\n".join(f"l{i}" for i in range(300))
        out = trim.trim_log(text, log=LOGPATH, cap=1024)
        assert len(out.encode()) <= 1024
        assert "FAIL: test_a" in out
        assert "AssertionError: boom" in out

    def test_zero_errors_is_no_failure_line(self):
        text = "\n".join(["    0 Error(s)", "Failed: 0"] * 5 + [f"line {i}" for i in range(100)] + ["done"])
        out = trim.trim_log(text, cap=600)
        assert "0 Error(s)" not in out

    def test_a_green_check_is_one_line_with_no_log(self):
        green = trim.green_line("just check", 12.4)
        assert green.count("\n") == 0
        assert green == "`just check` passed in 12 s"
        text = (FIX / "long_green.log").read_text()
        assert "PASS tests" not in green + text[:0]


class BriefPaths(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)
        (self.run_dir / "checks").mkdir()
        for f in FIX.glob("*.log"):
            (self.run_dir / "checks" / f.name).write_text(f.read_text())

    def teardown_method(self):
        self.tmp.cleanup()

    def test_failure_brief_trims_every_red_fixture_and_names_the_log(self):
        for name, must in MUST.items():
            with self.subTest(log=name):
                out = evidence.failure_brief([res(cmd="c", exit=1, log="checks/" + name)], self.run_dir)
                assert len(out.encode()) <= trim.CAP
                assert str(self.run_dir / "checks" / name) in out
                for line in must:  # a compiler's diagnostics are listed as file:line:col (diagnostics.py)
                    assert re.sub(r"\((\d+),(\d+)\)", r":\1:\2", line) in out

    def test_compact_red_keeps_the_failing_name_and_green_stays_one_line(self):
        tail = (FIX / "unittest_fail.log").read_text()[-1500:]
        red = evidence.compact([res(cmd="t", exit=1, group="tests", tail=tail)])
        assert red.count("\n") == 0
        assert len(red) <= 700
        assert "FAIL: test_refund_rounds" in red
        green = evidence.compact([res(cmd="t", exit=0, group="tests", tail=(FIX / "long_green.log").read_text()[-1500:])])
        assert green.count("\n") == 0

    def test_the_stored_log_is_not_changed(self):
        before = (self.run_dir / "checks" / "nunit_fail.log").read_text()
        evidence.failure_brief([res(cmd="c", exit=1, log="checks/nunit_fail.log")], self.run_dir)
        assert (self.run_dir / "checks" / "nunit_fail.log").read_text() == before



