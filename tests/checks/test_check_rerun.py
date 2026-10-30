"""CASEWRAP (tl-7k8.12): a plan check never runs a registered check again; it reads the saved log (procsim fakes, no real spawn)."""
import shlex
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.builders import cfg_with
from support.engine_case import CLEAN, PLAN, WRITE

from checks.test_check_rules import Base
from taskloop.domain.checks import lint

REPO: list[dict[str, Any]] = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}]
YXBB = "mkdir -p x && just unity-tests > x/out && grep -q passed x/out"


def plan_of(*checks: str) -> dict[str, Any]:
    return dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[shlex.join(shlex.split(c)) for c in checks])])


def reads_log(cwd: Path, env: Mapping[str, str]) -> tuple[int, str]:
    return (0, "") if "Passed: 12" in Path(env["TL_CHECK_LOG_UNITY_TESTS"]).read_text() else (1, "no pass line")


class Refused(unittest.TestCase):
    cfg = cfg_with(checks=REPO)

    def test_the_yxbb_chain_is_refused_naming_the_registered_check(self):
        got = lint.rerun_problems(plan_of(YXBB), self.cfg)
        self.assertEqual(len(got), 1)
        self.assertIn("runs the registered check `unity-tests` (`just unity-tests`) again", got[0])
        self.assertIn("$TL_CHECK_LOG_UNITY_TESTS", got[0])

    def test_the_recipe_with_arguments_a_subshell_a_sh_string_and_a_chain_are_refused(self):
        for c in ("just unity-tests --filter X", "just --unstable unity-tests", "env CI=1 just unity-tests",
                  "( just unity-tests )", "true ; just unity-tests", "just unity-tests | tee out",
                  "sh -c 'true && just unity-tests > out'", "bash -c '(just unity-tests)'"):
            self.assertEqual(len(lint.rerun_problems(plan_of(c), self.cfg)), 1, c)

    def test_a_mention_a_longer_recipe_and_a_log_read_are_not_refused(self):
        for c in ("echo 'just unity-tests'", "echo just unity-tests-extra", "just unity-tests-extra", "just fmt",
                  "grep -q passed /tmp/unity-tests.log", "sh -c 'echo \"just unity-tests\"'",
                  "python3 tools/assert_log.py TL_CHECK_LOG_UNITY_TESTS Passed"):
            self.assertEqual(lint.rerun_problems(plan_of(c), self.cfg), [], c)

    def test_a_case_is_judged_like_a_stage_check(self):
        plan = dict(PLAN, cases=[{"criterion": "c", "check": shlex.join(shlex.split(YXBB)), "class": "test"}])
        self.assertEqual(len(lint.rerun_problems(plan, self.cfg)), 1)


class Planned(Base):
    def test_the_refusal_reaches_the_planner_and_the_corrected_plan_runs(self):
        procsim.fake("just unity-tests", procsim.exits(0))
        bad = plan_of("just unity-tests --filter X")
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, checks=REPO)
        self.assertEqual([c[0] for c in s.calls][:2], ["planner", "planner"])
        self.assertIn("runs the registered check `unity-tests`", s.prompts[1])
        self.assertIn("TL_CHECK_LOG_UNITY_TESTS", s.prompts[1])


class ReadsTheLog(Base):
    def test_a_case_grepping_the_registered_log_passes_and_the_command_ran_once(self):
        procsim.fake("just unity-tests", procsim.exits(0, "Passed: 12"))
        reader = procsim.fake("assert-log TL_CHECK_LOG_UNITY_TESTS", reads_log)
        self.assertEqual(lint.rerun_problems(plan_of(reader), cfg_with(checks=REPO)), [])
        eng = self.checks_engine(checks=REPO)
        run = eng.run_checks({"checks": [reader], "files": []}, "s")
        self.assertEqual([c.status for c in run], ["passed", "passed"])
        self.assertEqual(procsim.ran("just unity-tests"), 1)


if __name__ == "__main__":
    unittest.main()
