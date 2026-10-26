"""Golden prompts (R05): the templates the engine sends, and the review prompt rendered the three ways it is.

A change to prompt text shows up here as a diff against tests/fixtures/prompts/*.txt; regenerate with
UPDATE_GOLDEN=1 python -m pytest tests/test_prompt_golden.py and commit the golden diff with the change."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import engine  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "prompts"
FIX_SCOPE = "the fix only: it must %s without breaking what the accepted stages built" % engine.Engine.FIX["gate"][0]
FIX_GOAL = "Fix: " + engine.Engine.FIX["gate"][0]


def render_review(fix=False, last=False):
    """REVIEW_PROMPT with the arguments Engine.stage passes, fixed values for everything else."""
    return engine.review_prompt(
        brief="<brief text>", plan="<plan text>", n=2, goal=FIX_GOAL if fix else "Add the greeting", work="<work: 1 file, +3 -0>",
        checks="<checks: all pass>", summary="<writer summary>", evidence=".task/t-1/evidence", gate=" (`just check`)",
        added=1, removed=0, fix=fix, last=last, fix_scope=FIX_SCOPE)


class Golden(unittest.TestCase):
    def check(self, name, text):
        path = GOLDEN / (name + ".txt")
        if os.environ.get("UPDATE_GOLDEN"):
            path.write_text(text, encoding="utf-8")
        self.assertEqual(path.read_text(encoding="utf-8"), text, "golden %s differs (UPDATE_GOLDEN=1 rewrites it)" % path.name)

    def test_templates(self):
        for name in ("PLAN_PROMPT", "WRITE_PROMPT", "WRITE_RESUME_PROMPT", "REVIEW_PROMPT", "VERIFY_PROMPT", "REFLECT_PROMPT"):
            with self.subTest(name):
                self.check("template-" + name.lower(), getattr(engine, name))

    def test_review_stage(self):
        self.check("review-stage", render_review())

    def test_review_last_stage(self):
        self.check("review-last", render_review(last=True))

    def test_review_fix_round(self):
        self.check("review-fix", render_review(fix=True, last=True))

    def test_fix_round_keeps_the_unmet_line_of_the_template(self):
        """tl-7y6.6.11: the fix scope was spliced into the unmet: sentence ('what in the fix only: it must ... the work does not do yet')."""
        line = lambda t: next(l for l in t.splitlines() if l.startswith("- unmet:"))
        fix = render_review(fix=True)
        self.assertEqual(line(fix), line(engine.REVIEW_PROMPT).format(scope="the stage goal"))
        self.assertNotIn("fix only", line(fix))
        self.assertIn("\nScope of this fix round: " + FIX_SCOPE + "\n", fix)
        self.assertNotIn("Scope of this fix round", render_review())


if __name__ == "__main__":
    unittest.main()
