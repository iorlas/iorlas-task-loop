"""The brief renderer: the text stays byte-identical to the golden set, and the section boundaries cover it exactly."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from plan.brief_cases import CASES, beads
from taskloop.app.asks import intake
from taskloop.app.plan.briefs import ENGINE_LABELS
from taskloop.domain.plan import brief as bf
from taskloop.domain.prompts.plan import PLAN_BRIEF_KB, PLAN_PROMPT

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "brief_golden"


def render(name: str) -> bf.Brief:
    bead, comments, owner_only = beads(name)
    hint = str(bead.metadata.get(intake.HINT) or "")
    return bf.render(bead, comments, intake.engine_written, hint, owner_only, (*ENGINE_LABELS, "tl-pick"))


class Golden(unittest.TestCase):
    def test_the_text_is_byte_identical_to_the_golden_set(self):
        for name in CASES:
            with self.subTest(name):
                self.assertEqual(render(name).text.encode(), (GOLDEN / f"{name}.md").read_bytes())

    def test_the_sections_tile_the_text_exactly(self):
        for name in CASES:
            with self.subTest(name):
                brief = render(name)
                raw = brief.text.encode()
                self.assertEqual(brief.sections[0].start, 0)
                self.assertEqual(brief.sections[-1].end, len(raw))
                for a, b in zip(brief.sections, brief.sections[1:], strict=False):
                    self.assertEqual(a.end, b.start)
                self.assertEqual(sum(brief.sizes().values()), len(raw))

    def test_a_section_names_what_it_costs(self):
        sizes = render("full").sizes()
        self.assertEqual(list(sizes)[:3], ["title", "meta", "description"])
        self.assertIn("comments", sizes)
        raw = render("full").text.encode()
        comments = next(s for s in render("full").sections if s.name == "comments")
        self.assertTrue(raw[comments.start:comments.end].decode().startswith("\n## Comments\n- denis"))

    def test_linked_beads_join_as_a_section_of_their_own(self):
        brief = render("full").plus("linked", bf.LINKED_HEAD + "- t-0 [open] The epic\n")
        self.assertEqual(brief.sizes()["linked"], len((bf.LINKED_HEAD + "- t-0 [open] The epic\n").encode()))
        self.assertEqual(sum(brief.sizes().values()), len(brief.text.encode()))


REPLAY = ("lifesim-5ban.28-20261022-234409", "lifesim-hclf.30-20261024-053813", "lifesim-yxbb.12-20261024-121436",
          "lifesim-r32-20261019-194636", "lifesim-rl2t-20261019-125141", "lifesim-d5f.61-20261022-231121")
# the six reflected runs of tl-r0e (5ban.28, hclf.34, rl4s, hclf.32, l4ow, yxbb.2) are not in the repo: these are the recorded briefs of
# the same project nearest to them in size (the named ones that are here, 5ban.28, and their neighbours hclf.30 and yxbb.12).


class PlannerBudget(unittest.TestCase):
    def test_the_planner_prompt_of_a_replayed_brief_stays_under_the_budget_with_room_for_the_rules(self):
        rules_room = 2 * 1024  # worker rules, notes and the where text ride after the brief
        for name in REPLAY:
            with self.subTest(name):
                brief = (Path(__file__).resolve().parents[1] / "fixtures" / "briefs" / f"{name}.md").read_text(encoding="utf-8")
                prompt = PLAN_PROMPT.format(brief=brief, wt="/work/tree")
                self.assertLess(len(prompt.encode()) + rules_room, PLAN_BRIEF_KB * 1024)


class Diff(unittest.TestCase):
    def test_a_field_diff_over_the_cap_is_cut_and_says_how_much_was_not_shown(self):
        out = bf.field_diff("line\n" * 2000 + "A", "line\n" * 2000 + "B\n" + "more\n" * 2000)
        self.assertIn("diff cut at 4 KB;", out)
        self.assertIn("more characters not shown", out)
        self.assertLessEqual(len(out), bf.DIFF_CAP + 120)
        self.assertEqual(bf.field_diff("a", "a"), "")


if __name__ == "__main__":
    unittest.main()
