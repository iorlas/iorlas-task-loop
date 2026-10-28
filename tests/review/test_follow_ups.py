"""The follow-up beads the engine files (E7c), through the real close path on the fake bd: no `auto` label, one `from:` label naming the
source bead and round, one bead per typed key (bead, category, file) and never more than the cap, the rest in one comment."""
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from support import engine_case as T  # noqa: E402
from taskloop.domain.review.followups import FOLLOW_UP_CAP, FollowKey  # noqa: E402
from support.engine_case import CLEAN, PLAN, WRITE, finding, review  # noqa: E402


def demand(n, file="f.txt", category="logic"):
    return dict(finding("high"), file=file, category=category, fix=f"close bead number {n}")


class FollowUps(unittest.TestCase):
    eng: Any
    store: Any
    setUp: Any = T.EngineTest.setUp
    tearDown: Any = T.EngineTest.tearDown
    commit_base_cfg: Any = T.EngineTest.commit_base_cfg
    fake_bd: Any = T.EngineTest.fake_bd
    run_engine: Any = T.EngineTest.run_engine

    def go(self, reviews=(CLEAN,), leftovers=()):
        rc, _ = self.run_engine({"plan": [dict(PLAN, leftovers=list(leftovers))], "write": [WRITE], "review": list(reviews)})
        self.assertEqual(rc, 0)
        return [c for c in self.store.calls if c[0] == "create"]

    def comments(self, start):
        return [c[3] for c in self.store.calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith(start)]

    @staticmethod
    def labels(create):
        return create[create.index("--labels") + 1].split(",") if "--labels" in create else []

    def test_a_filed_follow_up_has_one_from_label_and_never_auto(self):
        (made,) = self.go(leftovers=[{"title": "Rename x", "why": "w"}])
        labels = self.labels(made)
        self.assertEqual(len(labels), 1)
        self.assertRegex(labels[0], r"^from:t-1-r\d+$")
        self.assertIn("--no-inherit-labels", made)  # the source bead's own labels (auto) are not copied

    def test_two_findings_with_one_key_but_different_words_are_one_bead(self):
        made = self.go([review(findings=[demand(1), demand(2)]), CLEAN])
        self.assertEqual(len(made), 1)

    def test_findings_in_other_files_or_categories_are_other_beads(self):
        made = self.go([review(findings=[demand(1), demand(2, file="g.txt"), demand(3, category="docs")]), CLEAN])
        self.assertEqual(len(made), 3)

    def test_at_most_the_cap_are_filed_and_the_rest_are_one_comment(self):
        over = FOLLOW_UP_CAP + 2
        made = self.go([review(findings=[demand(i, file=f"f{i}.txt") for i in range(over)]), CLEAN])
        self.assertEqual(len(made), FOLLOW_UP_CAP)
        (note,) = self.comments("Follow-up (engine): not filed")
        self.assertIn(f"{over - FOLLOW_UP_CAP} more", note)

    def test_the_key_is_bead_category_and_file(self):
        a = FollowKey.of("t-1", {"title": "A", "why": "w", "category": "logic", "file": "f.txt"})
        b = FollowKey.of("t-1", {"title": "B", "why": "w", "category": "logic", "file": "f.txt"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, FollowKey.of("t-2", {"title": "A", "why": "w", "category": "logic", "file": "f.txt"}))


if __name__ == "__main__":
    unittest.main()
