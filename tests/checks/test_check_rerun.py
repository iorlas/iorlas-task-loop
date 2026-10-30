"""CASEWRAP (tl-7k8.12) and PLANREF (tl-3u6.2): a plan check is a Ref to a registered check or an Adhoc command that declares what it reads;
an Adhoc that wraps a registered check's command is refused at parse, naming the check (procsim fakes, no real spawn)."""
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
from support.checks import ck, typed
from support.engine_case import CLEAN, PLAN, WRITE

from checks.test_check_rules import Base
from taskloop.contracts import answers, plancheck
from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import Adhoc, PlanData, Ref, adhoc
from taskloop.domain.checks import planref

REPO: list[dict[str, Any]] = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}]
YXBB = "mkdir -p x && just unity-tests > x/out && grep -q passed x/out"
UNITY = CheckId("unity-tests")


def plan_of(*checks: Any) -> PlanData:
    return PlanData(**typed(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=list(checks))])))


def reads_log(cwd: Path, env: Mapping[str, str]) -> tuple[int, str]:
    return (0, "") if "Passed: 12" in Path(env["TL_CHECK_LOG_UNITY_TESTS"]).read_text() else (1, "no pass line")


def refusals(*checks: Any) -> list[str]:
    return planref.refusals(planref.plan_checks(plan_of(*checks)), cfg_with(checks=REPO))


class Parsed(unittest.TestCase):
    def test_a_planner_answer_with_a_ref_and_an_adhoc_parses(self):
        wire = plancheck.to_wire(PLAN)
        wire["stages"][0]["checks"] = [{"kind": "ref", "check": "unity-tests"},
                                       {"kind": "adhoc", "argv": ["python3", "tools/assert_log.py", "TL_CHECK_LOG_UNITY_TESTS"],
                                        "reads": ["unity-tests"]}]
        self.assertEqual(answers.check("plan", False, wire), [])
        plancheck.parse(wire)
        self.assertEqual(wire["stages"][0]["checks"], [Ref(check=UNITY), Adhoc(
            argv=("python3", "tools/assert_log.py", "TL_CHECK_LOG_UNITY_TESTS"), reads=(UNITY,))])

    def test_a_bare_argv_list_or_a_ref_with_reads_is_not_a_check(self):
        wire = plancheck.to_wire(PLAN)
        for bad in (["just", "check"], {"kind": "ref", "check": "x", "reads": []}, {"kind": "adhoc", "argv": ["x"]}):
            wire["stages"][0]["checks"] = [bad]
            self.assertTrue(answers.check("plan", False, wire), bad)

    def test_the_schema_offers_only_ref_or_adhoc(self):
        item = answers.schema_for("plan")["properties"]["stages"]["items"]["properties"]["checks"]["items"]
        kinds = sorted(m["properties"]["kind"]["enum"][0] for m in item["anyOf"])
        self.assertEqual(kinds, ["adhoc", "ref"])


class Refused(unittest.TestCase):
    def test_a_wrapper_is_refused_at_parse_naming_the_registered_check(self):
        got = refusals(adhoc("just unity-tests --filter X"))
        self.assertEqual(len(got), 1)
        self.assertIn("runs the registered check `unity-tests` (`just unity-tests`) again", got[0])
        self.assertIn("$TL_CHECK_LOG_UNITY_TESTS", got[0])
        self.assertIn("kind: ref", got[0])

    def test_the_recipe_with_arguments_flags_and_a_wrapper_program_are_refused(self):
        for c in ("just unity-tests --filter X", "just --unstable unity-tests", "env CI=1 just unity-tests", "just unity-tests"):
            self.assertEqual(len(refusals(adhoc(c))), 1, c)

    def test_a_mention_a_longer_recipe_and_a_declared_log_read_are_not_refused(self):
        for c in ("echo 'just unity-tests'", "echo just unity-tests-extra", "just unity-tests-extra", "just fmt",
                  "grep -q passed /tmp/unity-tests.log"):
            self.assertEqual(refusals(adhoc(c)), [], c)
        read = adhoc("python3 tools/assert_log.py TL_CHECK_LOG_UNITY_TESTS Passed", (UNITY,))
        self.assertEqual(refusals(read, Ref(check=UNITY)), [])

    def test_a_ref_or_a_read_of_a_check_the_repo_lacks_is_refused(self):
        self.assertIn("no such check", refusals(Ref(check=CheckId("nope")))[0])
        self.assertIn("reads `nope`", refusals(adhoc("true", (CheckId("nope"),)))[0])

    def test_a_case_is_judged_like_a_stage_check(self):
        plan = typed(dict(PLAN, cases=[{"criterion": "c", "check": shlex.join(shlex.split("just unity-tests -q")), "class": "test"}]))
        self.assertEqual(len(planref.refusals(planref.plan_checks(plan), cfg_with(checks=REPO))), 1)


class Planned(Base):
    def test_the_refusal_reaches_the_planner_and_the_corrected_plan_runs(self):
        procsim.fake("just unity-tests", procsim.exits(0))
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests --filter X"])])
        _rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, checks=REPO)
        self.assertEqual([c[0] for c in s.calls][:2], ["planner", "planner"])
        self.assertIn("runs the registered check `unity-tests`", s.prompts[1])
        self.assertIn("TL_CHECK_LOG_UNITY_TESTS", s.prompts[1])


class ReadsTheLog(Base):
    def test_a_case_reading_the_registered_log_passes_and_the_command_ran_once(self):
        procsim.fake("just unity-tests", procsim.exits(0, "Passed: 12"))
        reader = adhoc(procsim.fake("assert-log TL_CHECK_LOG_UNITY_TESTS", reads_log), (UNITY,))
        self.assertEqual(refusals(reader), [])
        eng = self.checks_engine(checks=REPO)
        run = eng.run_checks({"checks": ck([reader]), "files": []}, "s")
        self.assertEqual([c.status for c in run], ["passed", "passed"])
        self.assertEqual(procsim.ran("just unity-tests"), 1)


if __name__ == "__main__":
    unittest.main()
