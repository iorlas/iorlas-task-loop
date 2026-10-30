"""A check's tags are set once where the check is made; the plan, the conflict fix and the evidence read the tags, never the id or
command text again."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
import msgspec

from taskloop.contracts.checks import Check, CheckResult, Durations, Phase
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId
from taskloop.contracts.wire import load
from taskloop.domain.checks.plan import CheckPlan
from taskloop.domain.checks.specs import diff_check, gate_items, repo_check, tags_of, wall_limit


def chk(name: str, cmd: str = "true", **kw) -> Check:
    return Check(id=CheckId(name), cmd=cmd, repo=True, **kw)


class Tags(unittest.TestCase):
    def test_tags_come_from_the_id_and_command_once_at_the_edge(self):
        self.assertEqual(tags_of("unity-edit", "just unity"), ["unity"])
        self.assertEqual(tags_of("compile", "just build"), ["build"])
        self.assertEqual(tags_of("lint", "ruff"), [])
        k = CheckSpec(id=CheckId("play-unity"), argv=["x"])
        self.assertEqual(repo_check(k, EngineConfig()).tags, ["unity"])

    def test_an_unknown_tag_fails_to_parse(self):
        with self.assertRaises(ValueError):
            load(Check, {"id": "x", "cmd": "x", "tags": ["nonsense"]})

    def test_the_diff_check_carries_the_diff_tag(self):
        self.assertEqual(diff_check("b", "t").tags, ["diff"])
        self.assertEqual(CheckResult.skipped(diff_check("b", "t"), "why").tags, ["diff"])

    def test_the_plan_puts_a_unity_tagged_check_in_the_unity_group_whatever_its_text(self):
        plan = CheckPlan.build([chk("render", tags=["unity"]), chk("unity-lint")], Durations())
        self.assertEqual({s.check.id: s.unity for s in plan.steps}, {"render": True, "unity-lint": False})

    def test_a_conflict_fix_keeps_the_diff_and_build_tagged_checks_only(self):
        items = [diff_check("b", "t"), chk("compile", tags=["build"]), chk("build-docs"), chk("tests")]
        plan = CheckPlan.build(items, Durations(), conflict_fix=[], markers="m")
        self.assertEqual(sorted(s.check.id for s in plan.steps), ["compile", "diff-check"])
        self.assertEqual(sorted(r.id for r in plan.skipped), ["build-docs", "tests"])

    def test_a_check_called_diff_check_without_the_tag_is_not_the_engines(self):
        plan = CheckPlan.build([chk("diff-check")], Durations(), conflict_fix=[], markers="m")
        self.assertEqual(plan.steps, ())

    def test_tags_round_trip(self):
        c = chk("x", tags=["build"])
        self.assertEqual(msgspec.json.decode(msgspec.json.encode(c), type=Check).tags, ["build"])


class Phases(unittest.TestCase):
    def test_an_unknown_phase_fails_to_parse(self):
        self.assertEqual(Phase("gate"), Phase.GATE)
        with self.assertRaises(ValueError):
            Phase("land")

    def test_the_wall_limit_is_decided_by_the_phase_in_one_place(self):
        cfg = EngineConfig(check_wall_min=10, gate_timeout_min=45)
        k = CheckSpec(id=CheckId("t"), argv=["t"])
        own = CheckSpec(id=CheckId("o"), argv=["o"], wall_min=7)
        self.assertEqual((wall_limit(k, cfg, Phase.STAGE), wall_limit(k, cfg, Phase.GATE)), (10.0, 45.0))
        self.assertEqual((wall_limit(own, cfg, Phase.STAGE), wall_limit(own, cfg, Phase.GATE)), (7.0, 7.0))
        self.assertEqual(repo_check(k, cfg, Phase.GATE).wall_min, 45.0)
        self.assertEqual(repo_check(k, cfg).wall_min, 10.0)
        gated = EngineConfig(checks=[CheckSpec(id=CheckId("g"), argv=["g"], run="gate")], gate_timeout_min=33)
        self.assertEqual(gate_items(gated)[0].wall_min, 33.0)
