"""Golden prompts (R05): the templates the engine sends, and the review prompt rendered the three ways it is.

A change to prompt text shows up here as a diff against tests/fixtures/prompts/*.txt; regenerate with
UPDATE_GOLDEN=1 python -m pytest tests/test_prompt_golden.py and commit the golden diff with the change."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop.domain.prompts.review import acceptance_text  # noqa: E402
from taskloop.domain.prompts import common as cp  # noqa: E402
from taskloop.domain.prompts.land import FIX_GOAL  # noqa: E402
from taskloop.domain.prompts import plan as pp  # noqa: E402
from taskloop.domain.prompts import reflect as fp  # noqa: E402
from taskloop.domain.prompts import review as rp  # noqa: E402
from taskloop.domain.prompts import verify as vp  # noqa: E402
from taskloop.domain.prompts import write as wp  # noqa: E402
import engine  # noqa: E402
from support.builders import cfg_with  # noqa: E402
from taskloop.domain.checks.writer_split import WriterSplit  # noqa: E402

TEMPLATES = {"PLAN_PROMPT": pp, "WRITE_PROMPT": wp, "WRITE_RESUME_PROMPT": wp, "REVIEW_PROMPT": rp, "VERIFY_PROMPT": vp, "REFLECT_PROMPT": fp}
GOLDEN = ROOT / "tests" / "fixtures" / "prompts"
FIX_SCOPE = "the fix only: it must %s without breaking what the accepted stages built" % FIX_GOAL["gate"]
FIX_GOAL = "Fix: " + FIX_GOAL["gate"]


def render_review(fix=False, last=False):
    """REVIEW_PROMPT with the arguments Engine.stage passes, fixed values for everything else."""
    return rp.review_prompt(
        brief="<brief text>", plan="<plan text>", n=2, goal=FIX_GOAL if fix else "Add the greeting", work="<work: 1 file, +3 -0>",
        checks="<checks: all pass>", summary="<writer summary>", evidence=".task/t-1/evidence", gate=" (`just check`)",
        added=1, removed=0, fix=fix, last=last, fix_scope=FIX_SCOPE, acceptance=acceptance_text([("A1", "greets by name")]) if last else "")


RULES = "Unity runs on the host, not in a sandbox.\nNever run `just check`: the engine does."
CHECKS = ["python3 -m unittest tests.test_f", "just unity-tests"]


def stub_engine(rules="worker-rules.md"):
    """An Engine with a config and no run: enough to render the writer's check lists."""
    eng = engine.Engine.__new__(engine.Engine)
    eng.cfg = cfg_with(gate="just check", worker_rules=rules, checks=[{"id": "fmt", "cmd": "just fmt-check", "group": "static"}])
    setattr(eng, "checker", SimpleNamespace(split=lambda: WriterSplit(eng.cfg, {})))  # noqa: B010
    return eng


def render_write(rules=RULES, failed=None):
    """The stage-1 write prompt as Engine.stage builds it: stage checks, where text, rules inlined."""
    eng = stub_engine()
    where = eng.where("write", [c.cmd for c in eng.cfg.checks] + CHECKS, failed, listed=CHECKS)
    return wp.write_prompt(
        rules, brief="<brief text>", plan="<plan text>", n=1, goal="Add the greeting", files="greet.py", anchors="",
        checks=eng.stage_checks_text(CHECKS, skip=failed), feedback="", evidence=".task/t-1/evidence", where=where, gate=" (`just check`)")


def render_resume(failed=None):
    """The delta a resumed writer gets (Engine.write_delta) for the same stage."""
    eng = stub_engine()
    where = eng.where("write", [c.cmd for c in eng.cfg.checks] + CHECKS, failed, listed=CHECKS)
    return wp.WRITE_RESUME_PROMPT.format(
        brief=".task/t-1/brief.md", plan="The plan is unchanged.", n=1, goal="Add the greeting", files="greet.py", anchors="",
        checks=eng.stage_checks_text(CHECKS, skip=failed), where=where, feedback="")


class Golden(unittest.TestCase):
    def check(self, name, text):
        path = GOLDEN / (name + ".txt")
        if os.environ.get("UPDATE_GOLDEN"):
            path.write_text(text, encoding="utf-8")
        self.assertEqual(path.read_text(encoding="utf-8"), text, "golden %s differs (UPDATE_GOLDEN=1 rewrites it)" % path.name)

    def test_templates(self):
        for name, module in TEMPLATES.items():
            with self.subTest(name):
                self.check("template-" + name.lower(), getattr(module, name))

    def test_write_prompt(self):
        self.check("write-first", render_write())

    def test_write_prompt_after_a_red_round(self):
        self.check("write-red", render_write(failed=["just unity-tests", "just fmt-check"]))

    def test_write_prompt_without_rules(self):
        self.assertNotIn("worker_rules", render_write(rules=""))

    def test_resumed_write_delta(self):
        self.check("write-resume", render_resume())

    def test_fresh_writer_prompt_carries_the_rules_and_what_was_done(self):
        text = render_write() + wp.DONE_SO_FAR % (" greet.py | 3 +++", "wrote the greeting", "(none)\n")
        self.check("write-fresh", text)

    def test_rules_are_inlined_once_and_no_prompt_names_codex_md(self):
        full = render_write()
        self.assertEqual(full.count(RULES), 1)
        self.assertLessEqual(len(RULES.encode("utf-8")), cp.RULES_MAX)
        resume = render_resume()
        self.assertNotIn("Read ", resume)
        self.assertNotIn(RULES, resume)
        self.assertNotIn("worker_rules", resume)
        every = [getattr(module, n) for n, module in TEMPLATES.items()] + [wp.WRITE_RULES, wp.DONE_SO_FAR, wp.STAGES_DONE]
        for text in every + [full, resume, render_review(), render_review(last=True), render_review(fix=True, last=True)]:
            self.assertNotIn("codex.md", text)

    def test_each_check_command_is_named_once_in_the_may_run_lists(self):
        for failed in (None, ["just unity-tests"], ["python3 -m unittest tests.test_f", "just fmt-check"]):
            for text in (render_write(failed=failed), render_resume(failed=failed)):
                with self.subTest(failed=failed):
                    lists = text[text.index("The stage's checks"):text.index("If a command is refused")]
                    for cmd in CHECKS + ["just fmt-check"]:
                        self.assertLessEqual(lists.count("- " + cmd), 1, cmd)
                    if failed is None:  # the whole list: every command named, once
                        for cmd in CHECKS + ["just fmt-check"]:
                            self.assertEqual(lists.count("- " + cmd), 1, cmd)

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
        self.assertEqual(line(fix), line(rp.REVIEW_PROMPT).format(scope="the stage goal"))
        self.assertNotIn("fix only", line(fix))
        self.assertIn("\nScope of this fix round: " + FIX_SCOPE + "\n", fix)
        self.assertNotIn("Scope of this fix round", render_review())


if __name__ == "__main__":
    unittest.main()
