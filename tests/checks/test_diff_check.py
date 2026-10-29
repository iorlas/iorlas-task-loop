"""The engine's own check: `git diff --check` over the stage's diff, first in every round, quiet when clean."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import PY, EngineTest, shq
from support.narrow import must

# isort: split
from taskloop.app.checks import evidence
from taskloop.domain.checks import matchers

ST = {"checks": [], "files": []}
TESTS = {"id": "unit", "cmd": PY + " -c " + shq("print('unit ran')"), "group": "tests"}


class DiffCheckTest(EngineTest):
    def red(self, text):
        eng = self.checks_engine(checks=[TESTS])
        (self.wt / "f.txt").write_text(text)
        return eng, eng.run_checks(ST, "s")

    def test_a_conflict_marker_in_the_diff_fails_with_gits_file_and_line(self):
        _, run = self.red("a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> t\n")
        first = run[0]
        self.assertEqual((first.id, first.status, first.group), ("diff-check", "failed", "static"))
        self.assertIn("f.txt:2: leftover conflict marker", first.tail)
        self.assertEqual([(c.id, c.status) for c in run][1:], [("unit", "skipped")])  # cheap red: the expensive check did not run

    def test_trailing_whitespace_on_a_changed_line_fails_the_same_way(self):
        _, run = self.red("ok\nbad  \n")
        self.assertEqual(run[0].status, "failed")
        self.assertIn("f.txt:2: trailing whitespace.", run[0].tail)
        self.assertIn("+bad  ", run[0].tail)

    def test_a_clean_diff_passes_and_adds_nothing_to_the_writers_text(self):
        eng, run = self.red("fine\n")
        self.assertEqual([c.id for c in run], ["unit"])
        self.assertEqual(run[0].status, "passed")
        self.assertNotIn("diff", evidence.compact(run.results) + evidence.failure_brief(run.failed, eng.run_dir))

    def test_the_same_tree_and_base_is_not_checked_twice(self):
        eng = self.checks_engine(checks=[TESTS])
        (self.wt / "f.txt").write_text("good\n")
        eng.run_checks(ST, "s")
        eng.run_checks(ST, "s")  # same tree and base: a green is cached
        self.assertEqual(self.ran(), 1)
        (self.wt / "f.txt").write_text("good too\n")
        eng.run_checks(ST, "s")
        self.assertEqual(self.ran(), 2)

    def ran(self):
        return sum(1 for c in must(self.sim).calls if c[:2] == ("diff", "--check"))

    def test_the_writers_text_is_capped_at_20_lines_then_a_count(self):
        eng, run = self.red("".join(f"<<<<<<< x{n}\n" for n in range(30)))
        lines = run[0].tail.splitlines()
        self.assertEqual(len(lines), 21)
        self.assertEqual(lines[-1], "and 10 more in 1 file")
        self.assertIn("and 10 more in 1 file", evidence.failure_brief(run.failed, eng.run_dir))

    def test_the_cap_counts_files(self):
        out = "\n".join(f"{p}:{n}: leftover conflict marker" for p, k in (("a", 10), ("b", 10), ("c", 3), ("d", 3))
                        for n in range(1, k + 1))
        self.assertTrue(matchers.diff_check_text(out).endswith("and 6 more in 2 files"))
        self.assertEqual(matchers.diff_check_text("a:1: trailing whitespace.\n+x  "), "a:1: trailing whitespace.\n+x  ")
