"""tl-7y6.7.1 / .7.2: the bead rule table (a fixture per rule), `tl lint`, and the loop's once-only refusal of a failing bead."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import looptest
from support.fakes import FakeBeadStore, as_bead
from support.narrow import must
from loop.test_loop import LoopBase, bead, rec

from taskloop.app.loop import lintrun
from taskloop.domain.beads import rules

GOOD = {"id": "t-1", "title": "t", "status": "open", "issue_type": "task", "description": "do it", "acceptance_criteria": "- it works"}


def fails(children=False, **f):
    return [x.rule for x in rules.failures(must(as_bead(dict(GOOD, **f))), "/repo", lambda: children)]


class Rules(unittest.TestCase):
    def test_a_good_bead_passes(self):
        self.assertEqual(fails(), [])

    def test_r1_needs_a_description(self):
        self.assertEqual(fails(description="  "), ["R1"])

    def test_r2_needs_acceptance_criteria_in_the_field_or_a_heading(self):
        self.assertEqual(fails(acceptance_criteria=""), ["R2"])
        self.assertEqual(fails(acceptance_criteria="", description="goal\n\n## Acceptance Criteria\n- x"), [])

    def test_r3_touches_names_at_most_eight_paths(self):
        nine = ", ".join(f"a/{i}.py" for i in range(9))
        self.assertEqual(fails(description=f"goal\nTouches: {nine}"), ["R3"])
        self.assertEqual(fails(description="goal\nTouches: " + nine.rsplit(",", 1)[0]), [])
        bullets = "\n".join(f"- a/{i}.py" for i in range(9))
        self.assertEqual(fails(description=f"goal\n## Touches\n{bullets}\n\nmore"), ["R3"])
        self.assertEqual(fails(description="goal, no field"), [])

    def test_r5_an_epic_with_children_is_a_container(self):
        self.assertEqual(fails(children=True, issue_type="epic"), ["R5"])
        self.assertEqual(fails(children=False, issue_type="epic"), [])
        self.assertEqual(fails(children=True, issue_type="task"), [])

    def test_r6_a_decision_is_never_work_and_a_spike_needs_an_output_file(self):
        self.assertEqual(fails(issue_type="decision"), ["R6"])
        self.assertEqual(fails(issue_type="spike"), ["R6"])
        self.assertEqual(fails(issue_type="spike", description="goal\nOutput: docs/spike.md"), [])

    def test_the_facts_rule_stays_in_the_table(self):
        self.assertEqual(fails(description="see ~/Documents/Drop/x.md"), ["FACTS"])

    def test_why_joins_every_failed_rule_on_one_line(self):
        b = must(as_bead({"id": "t-2", "title": "t", "status": "open"}))
        self.assertEqual(rules.why(b), "R1: no description (goal); R2: no acceptance criteria")


class Verb(unittest.TestCase):
    def run_lint(self, store, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = lintrun.lint_ready(store, "/repo", kw.get("fix", False)) if kw.get("ready") else lintrun.lint_one(store, "/repo", "t-1")
        return rc, out.getvalue()

    def test_one_bead_prints_pass_or_a_line_per_failed_rule(self):
        self.assertEqual(self.run_lint(FakeBeadStore().put(GOOD)), (0, "t-1 pass\n"))
        rc, out = self.run_lint(FakeBeadStore().put(dict(GOOD, description="", acceptance_criteria="")))
        self.assertEqual((rc, out.splitlines()), (1, ["t-1 R1: no description (goal)", "t-1 R2: no acceptance criteria"]))

    def test_ready_marks_auto_and_fix_swaps_auto_for_needs_ac(self):
        store = FakeBeadStore().put(dict(GOOD, id="t-1", labels=["auto"], acceptance_criteria=""))
        store.put(dict(GOOD, id="t-2", labels=["auto"]))
        rc, out = self.run_lint(store, ready=True)
        self.assertEqual(rc, 1)
        self.assertIn("t-1", out)
        self.assertEqual(store.calls, [])
        rc, out = self.run_lint(store, ready=True, fix=True)
        self.assertEqual(rc, 0)
        self.assertEqual(store.calls, [("label", "remove", "t-1", "auto"), ("label", "add", "t-1", "needs-ac")])
        self.assertIn("t-1: removed auto", out)


class Refusal(LoopBase):
    """Beads shaped like tl-pg0 (no acceptance), an epic with children and a decision are never claimed."""

    def test_failing_beads_are_never_claimed_and_are_labelled_and_commented_once(self):
        shaped = [dict(bead("x-1"), acceptance_criteria=""), dict(bead("x-3"), issue_type="decision"), bead("x-4")]
        bd = self.bd = self.fake(*shaped, bead("x-2", type="epic"), slots=2)
        self.script = {"x-4": [rec("landed")]}
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-4"])
        self.assertFalse([c for c in bd.calls if c[:2] == ("update", "x-1") and "--claim" in c])
        for bid in ("x-1", "x-3"):
            self.assertEqual(sum(c == ("label", "add", bid, "needs-ac") for c in bd.calls), 1, bid)
            self.assertEqual(sum(c[:3] == ("comments", "add", bid) for c in bd.calls), 1, bid)
        self.assertEqual(self.out.count("skip x-1:"), 1)

    def test_a_bead_that_already_has_the_label_gets_no_second_comment(self):
        bd = self.fake(dict(bead("x-1", labels=["needs-ac"]), acceptance_criteria=""), slots=2)
        self.run_loop()
        self.assertFalse([c for c in bd.calls if c[0] in ("comments", "label")])
        self.assertEqual(looptest.queue(str(self.repo))[1], [("x-1", "R2: no acceptance criteria")])


if __name__ == "__main__":
    unittest.main()
