"""CHECKPATH: missing check executables replan before any writer; only earlier producers exempt an output."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.builders import cfg_with
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest

from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import PlanCheck, PlanData, Ref, StageData, adhoc
from taskloop.contracts.ports import TreeProbe
from taskloop.domain.checks import lint

OUTPUT = "tests/Sim.Scenarios/bin/Debug/net10.0/Sim.Scenarios"
TYPO = "tests/Sim.Scenarios/bin/Debug/net10.0/Sim.Scenenarios"
BUILD = "dotnet build tests/Sim.Scenarios/Sim.Scenarios.csproj"


def stage(*commands: str, files: tuple[str, ...] = ()) -> StageData:
    checks: list[PlanCheck] = [adhoc(c) for c in commands]
    return StageData(files=list(files), checks=checks)


class CheckPaths(unittest.TestCase):
    def setUp(self):
        self.probe = mock.Mock(spec=TreeProbe)
        self.probe.exists.return_value = False
        self.probe.is_dir.return_value = False
        self.probe.has_command.return_value = True

    def problems(self, *stages: StageData) -> list[str]:
        return lint.dry_check(PlanData(stages=list(stages)), self.probe)

    def test_a_missing_executable_is_named_even_when_its_top_folder_is_absent(self):
        for path in (TYPO, "./missing/tool", "/missing/tool", ".venv/bin/python", "~/missing/tool"):
            with self.subTest(path=path):
                errors = self.problems(stage(path))
                self.assertEqual(len(errors), 1)
                self.assertIn("CHECKPATH:", errors[0])
                self.assertIn(path, errors[0])

    def test_an_existing_file_is_allowed_but_a_directory_is_rejected(self):
        self.probe.exists.return_value = True
        self.assertEqual(self.problems(stage(OUTPUT)), [])
        self.probe.is_dir.return_value = True
        self.assertIn("CHECKPATH:", self.problems(stage(OUTPUT))[0])

    def test_an_existing_file_without_execute_permission_is_rejected(self):
        self.probe.exists.return_value = True
        self.probe.has_command.return_value = False
        self.assertIn("CHECKPATH:", self.problems(stage(OUTPUT))[0])

    def test_a_build_output_is_exempt_only_when_the_earlier_build_produces_that_path(self):
        self.assertEqual(self.problems(stage(BUILD, OUTPUT)), [])
        self.assertEqual(self.problems(stage(BUILD), stage(OUTPUT)), [])
        for commands in ((BUILD, TYPO), (OUTPUT, BUILD), ("echo build", OUTPUT),
                         (BUILD + " -c Release", OUTPUT), (BUILD + " -f net8.0", OUTPUT)):
            with self.subTest(commands=commands):
                self.assertTrue(any("CHECKPATH:" in e for e in self.problems(stage(*commands))))

    def test_an_explicit_compiler_output_is_exempt_but_an_unrelated_output_is_not(self):
        self.assertEqual(self.problems(stage("cc source.c -o ./out/tool", "./out/tool")), [])
        self.assertTrue(self.problems(stage("cc source.c -o ./out/tool", "./out/typo")))
        self.assertEqual(self.problems(stage(BUILD + " --output out", "./out/Sim.Scenarios")), [])
        self.assertTrue(self.problems(stage(BUILD + " --output out", "./out/Sim.Scenenarios")))

    def test_a_writer_can_create_the_executable_but_a_later_stage_cannot_supply_it(self):
        self.assertEqual(self.problems(stage(OUTPUT, files=(OUTPUT,))), [])
        self.assertEqual(self.problems(stage(files=(OUTPUT,)), stage(OUTPUT)), [])
        self.assertIn("CHECKPATH:", self.problems(stage(OUTPUT), stage(files=(OUTPUT,)))[0])

    def test_wrapped_executables_and_case_checks_are_validated(self):
        self.assertIn("CHECKPATH:", self.problems(stage("env CI=1 " + TYPO))[0])
        data = PlanData(stages=[stage(BUILD)], cases=[{"criterion": "runs", "check": adhoc(OUTPUT)}])
        self.assertEqual(lint.dry_check(data, self.probe), [])
        data["cases"][0]["check"] = adhoc(TYPO)
        self.assertIn("CHECKPATH:", lint.dry_check(data, self.probe)[0])

    def test_a_registered_build_can_produce_the_executable(self):
        cfg = cfg_with(checks=[{"id": "build", "cmd": BUILD, "group": "tests"}])
        data = PlanData(stages=[StageData(files=[], checks=[Ref(check=CheckId("build")), adhoc(OUTPUT)])])
        self.assertEqual(lint.dry_check(data, self.probe, cfg), [])
        data["stages"][0]["checks"] = [adhoc(OUTPUT, (CheckId("build"),))]
        self.assertEqual(lint.dry_check(data, self.probe, cfg), [])


class BeforeWriters(EngineTest):
    def bad_plan(self):
        return dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[TYPO])])

    def test_the_typo_is_sent_back_before_dispatching_the_writer(self):
        rc, script = self.run_engine({"plan": [self.bad_plan(), PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in script.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("CHECKPATH:", script.prompts[1])
        self.assertIn(TYPO, script.prompts[1])

    def test_an_uncorrected_typo_stops_as_a_plan_failure_without_a_writer(self):
        rc, script = self.run_engine({"plan": [self.bad_plan(), self.bad_plan()]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in script.calls], ["planner", "planner"])
        self.assertIn("CHECKPATH", self.said())
