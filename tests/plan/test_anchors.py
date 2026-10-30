"""Plan v2: a stage's anchors, how the writer reads them, and what the planner is sent back for."""
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import answers
from taskloop.domain.plan.stored import role_view, stored
from taskloop.domain.prompts.anchors import anchors_text, unanchored

ANCHOR = {"path": "src/a.py", "lines": "10-40", "symbol": "Thing.run", "why": "the loop to change"}
STAGE = {"goal": "g", "files": ["src/a.py", "src/new.py"], "anchors": [ANCHOR], "read_first": ["docs/a.md"],
         "patterns": ["see src/b.py"], "constraints": "keep the public API"}


class Rendering(unittest.TestCase):
    def test_a_stage_renders_its_anchors_read_first_patterns_and_constraints(self):
        self.assertEqual(anchors_text(STAGE), "Anchors (start here; the planner already read these):\n"
                         "- src/a.py:10-40 Thing.run -- the loop to change\nRead first: docs/a.md\n"
                         "Follow these patterns:\n- see src/b.py\nConstraints: keep the public API\n")

    def test_a_stage_without_them_renders_nothing(self):
        self.assertEqual(anchors_text({"goal": "g", "files": ["a"], "constraints": None, "anchors": None}), "")

    def test_an_existing_file_no_anchor_names_is_unanchored(self):
        self.assertEqual(unanchored(STAGE, {"src/a.py": True, "src/new.py": True}), ["src/new.py"])
        self.assertEqual(unanchored(STAGE, {"src/a.py": True, "src/new.py": False}), [])  # a new file has nothing to anchor


class Contract(unittest.TestCase):
    PLAN: ClassVar[Any] = {
        "summary": "s",
        "stages": [dict(STAGE, checks=[{"kind": "adhoc", "argv": ["true"], "reads": []}], hard=False)],
        "risks": [],
        "question": "",
        "options": [],
        "decided": "",
        "cases": [],
        "leftovers": [],
    }

    def test_the_plan_schema_carries_the_new_stage_fields(self):
        stage = answers.sent_schema("plan", False)["properties"]["stages"]["items"]
        self.assertTrue({"anchors", "read_first", "patterns", "constraints"} <= set(stage["required"]))
        self.assertEqual(sorted(stage["properties"]["anchors"]["items"]["required"]), ["lines", "path", "symbol", "why"])

    def test_a_plan_with_anchors_is_valid_and_one_without_them_still_is(self):
        self.assertEqual(answers.check("plan", False, self.PLAN), [])
        bare = {
            **self.PLAN,
            "stages": [{k: v for k, v in self.PLAN["stages"][0].items() if k not in ("anchors", "read_first", "patterns")}],
        }
        self.assertEqual(answers.check("plan", False, bare), [])

    def test_a_writer_handoff_over_a_kilobyte_is_refused(self):
        write = {"summary": "s", "checks_run": [], "question": "", "options": [], "decided": "", "bad_checks": [], "new_cases": [],
                 "unchecked": []}
        self.assertEqual(answers.check("write", False, dict(write, handoff="x" * 1024)), [])
        self.assertIn("handoff", answers.check("write", False, dict(write, handoff="x" * 1025))[0])


class Stored(unittest.TestCase):
    def test_the_stored_plan_drops_what_only_the_accept_step_reads(self):
        plan = {"summary": "s", "question": "", "options": [], "decided": "d", "unresolved": [], "risks": [],
                "stages": [{"goal": "g", "files": ["a"], "checks": [["true"]], "hard": True}]}
        self.assertEqual(stored(plan), {"summary": "s", "risks": [], "stages": [{"goal": "g", "files": ["a"], "checks": [["true"]]}]})

    def test_a_writer_sees_its_own_stage_whole_and_the_others_by_goal(self):
        plan = {"summary": "s", "assumptions": [{"text": "x"}], "risks": [{"what": "r"}], "cases": [{"criterion": "c"}], "leftovers": [],
                "stages": [{"goal": "one", "files": ["a"], "checks": [["t1"]]}, {"goal": "two", "files": ["b"], "checks": [["t2"]]}]}
        view = role_view(plan, 1)
        self.assertEqual(view["stages"], [{"goal": "one", "files": ["a"]}, plan["stages"][1]])
        self.assertEqual(sorted(view), ["assumptions", "stages", "summary"])


if __name__ == "__main__":
    unittest.main()
