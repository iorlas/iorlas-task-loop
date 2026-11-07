"""The engine's own check: `git diff --check` over the stage's diff, first in every round, quiet when clean."""
from support.check_host import CheckHostCase

from tltestkit import procsim
from tltestkit.narrow import must

# isort: split
from tlgate import evidence
from tlkernel import checkmatchers as matchers

ST = {"checks": [], "files": []}
TESTS = {"id": "unit", "cmd": procsim.default("unit-tests", procsim.exits(0, "unit ran")), "group": "tests"}


class DiffCheckTest(CheckHostCase):
    def red(self, text):
        eng = self.checks_engine(checks=[TESTS])
        (self.wt / "f.txt").write_text(text)
        return eng, eng.run_checks(ST, "s")

    def test_a_conflict_marker_in_the_diff_fails_with_gits_file_and_line(self):
        _, run = self.red("a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> t\n")
        first = run[0]
        assert (first.id, first.status, first.group) == ("diff-check", "failed", "static")
        assert "f.txt:2: leftover conflict marker" in first.tail
        assert [(c.id, c.status) for c in run][1:] == [("unit", "skipped")]  # cheap red: the expensive check did not run

    def test_trailing_whitespace_on_a_changed_line_fails_the_same_way(self):
        _, run = self.red("ok\nbad  \n")
        assert run[0].status == "failed"
        assert "f.txt:2: trailing whitespace." in run[0].tail
        assert "+bad  " in run[0].tail

    def test_a_clean_diff_passes_and_adds_nothing_to_the_writers_text(self):
        eng, run = self.red("fine\n")
        assert [c.id for c in run] == ["unit"]
        assert run[0].status == "passed"
        assert "diff" not in evidence.compact(run.results) + evidence.failure_brief(run.failed, eng.run_dir)

    def test_the_same_tree_and_base_is_not_checked_twice(self):
        eng = self.checks_engine(checks=[TESTS])
        (self.wt / "f.txt").write_text("good\n")
        eng.run_checks(ST, "s")
        eng.run_checks(ST, "s")  # same tree and base: a green is cached
        assert self.ran() == 1
        (self.wt / "f.txt").write_text("good too\n")
        eng.run_checks(ST, "s")
        assert self.ran() == 2

    def ran(self):
        return sum(1 for c in must(self.sim).calls if c[:2] == ("diff", "--check"))

    def test_the_writers_text_is_capped_at_20_lines_then_a_count(self):
        eng, run = self.red("".join(f"<<<<<<< x{n}\n" for n in range(30)))
        lines = run[0].tail.splitlines()
        assert len(lines) == 21
        assert lines[-1] == "and 10 more in 1 file"
        assert "and 10 more in 1 file" in evidence.failure_brief(run.failed, eng.run_dir)

    def test_the_cap_counts_files(self):
        out = "\n".join(f"{p}:{n}: leftover conflict marker" for p, k in (("a", 10), ("b", 10), ("c", 3), ("d", 3))
                        for n in range(1, k + 1))
        assert matchers.diff_check_text(out).endswith("and 6 more in 2 files")
        assert matchers.diff_check_text("a:1: trailing whitespace.\n+x  ") == "a:1: trailing whitespace.\n+x  "
