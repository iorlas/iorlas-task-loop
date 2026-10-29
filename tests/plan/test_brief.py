"""The brief renderer: the text stays byte-identical to the golden set, and the section boundaries cover it exactly."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

import taskloop.app.plan.briefs as mod
from plan.brief_cases import CASES, beads
from taskloop.app.asks import intake
from taskloop.app.plan.briefs import ENGINE_LABELS, Briefs
from taskloop.contracts.bead import Bead, Comment
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


class FitsTheLimit(unittest.TestCase):
    def brief(self, bead: Bead, comments: list[Comment], kb: float = 5) -> bf.Brief:
        host = SimpleNamespace(cfg=SimpleNamespace(brief_kb=kb))
        return Briefs(host).fit(bead, comments, "", 0)

    def test_a_brief_that_grows_over_five_reruns_stays_under_the_limit_oldest_comments_first(self):
        bead = Bead(id="t-1", title="Add f", status="open", description="Add the file f.", acceptance_criteria="f exists")
        comments: list[Comment] = []
        for rerun in range(1, 6):
            comments.append(Comment(author="denis", text=f"decision {rerun}: " + "x" * 2000))
            out = self.brief(bead, comments)
            with self.subTest(rerun=rerun):
                self.assertLess(len(out.text.encode()), 5 * 1024)
                self.assertIn("Add the file f.", out.text)
                self.assertIn("f exists", out.text)
                self.assertIn(f"decision {rerun}:", out.text)  # the newest stays
        self.assertNotIn("decision 1:", out.text)
        self.assertEqual(out.dropped, 3)
        self.assertIn("(+3 older comments left out", out.text)
        self.assertLess(out.text.index("(+3"), out.text.index("decision 4:"))

    def test_the_newest_comment_stays_even_when_it_alone_is_over_the_limit(self):
        out = self.brief(Bead(id="t-1", title="T", status="open"), [Comment(author="a", text="old"), Comment(author="a", text="n" * 9000)])
        self.assertIn("n" * 9000, out.text)
        self.assertNotIn("- a: old", out.text)

    def test_a_bead_text_over_the_limit_is_never_cut_and_the_comments_all_go_but_the_newest(self):
        bead = Bead(id="t-1", title="T", status="open", description="d" * 7000)
        out = self.brief(bead, [Comment(author="a", text="one"), Comment(author="a", text="two")])
        self.assertIn("d" * 7000, out.text)
        self.assertEqual(out.dropped, 1)

    def test_export_warns_naming_the_bead_text_size_when_the_text_alone_is_over_the_limit(self):
        bead = Bead(id="t-1", title="T", status="open", description="d" * 7000)
        warns, notes = [], []
        with tempfile.TemporaryDirectory() as d:
            store = SimpleNamespace(comments=lambda i: [Comment(author="a", text="one"), Comment(author="a", text="two")],
                                    show=lambda i: bead)
            host = SimpleNamespace(
                cfg=SimpleNamespace(brief_kb=5, pick_label="", needs_info_label=""), store=store, bead="t-1", run_dir=Path(d),
                brief_file=Path(d) / "b.md", answered=None, warn=warns.append, log=SimpleNamespace(note=notes.append),
                planner=SimpleNamespace(cap=SimpleNamespace(answered_words=lambda: "")))
            with mock.patch.object(mod, "peek", lambda store, bead_id: bead):
                Briefs(host).export()
        self.assertEqual(len(warns), 1)
        self.assertIn("bead's own text is 7 KB", warns[0])
        self.assertIn("1 oldest comments left out", notes[0])


if __name__ == "__main__":
    unittest.main()
