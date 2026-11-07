"""Whole beads through the Engine, moved out of tests/checks/test_check_trim.py (they run the pipeline, not only the checks stage)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support.engine_case import EngineTest  # noqa: E402
from support.plans import CLEAN, PLAN, WRITE  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from tlkernel import checktrim as trim  # noqa: E402
from tltestkit import procsim  # noqa: E402

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



class RedCheckPrompt(EngineTest):
    """The writer's prompt after a red check carries the trimmed form, not the log."""

    def test_the_second_write_sees_failure_lines_and_the_log_path_not_the_whole_log(self):
        def noisy(cwd, env):
            lines = [f"setup step {i} ok, nothing to see here" for i in range(600)]
            lines += ["FAIL: test_refund_rounds (tests.test_orders.OrderTests)", "AssertionError: 10.04 != 10.05"]
            lines += [f"teardown {i}" for i in range(80)]
            return (0 if procsim.f_txt(cwd) == "d3" else 1), "\n".join(lines)
        check = procsim.fake("noisy-check", noisy)
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        writes = [p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker"]
        assert len(writes) == 2
        second = writes[1]
        assert "These checks fail" in second
        assert "FAIL: test_refund_rounds" in second
        assert "AssertionError: 10.04 != 10.05" in second
        assert ".log" in second  # the path of the full log
        assert "setup step 300 ok" not in second
        assert "setup step 598 ok" not in second  # only the line before the failure comes with it
        assert len(second) - len(writes[0]) < 2 * trim.CAP
        assert "setup step" not in writes[0]  # the first write has no check output at all
