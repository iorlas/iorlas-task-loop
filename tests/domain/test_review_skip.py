"""domain/review/skip.py: a stage's review is skipped only when every changed path is mechanical; one other path means review."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import config
from taskloop.contracts.config import ReviewSkipConfig
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.domain.review.skip import SkipKind, decide

RULES = ReviewSkipConfig(config=["config/*.json"], generated=["gen/**"], tools=["tools/**"], tests=["tests/**"])


def mod(path: str) -> DiffEntry:
    return DiffEntry(status="M", path=path)


def go(*entries: DiffEntry, loud: tuple[str, ...] | None = None, formatter: bool = True, rules: ReviewSkipConfig = RULES):
    significant = frozenset(e.path for e in entries) if loud is None else frozenset(loud)
    return decide(list(entries), significant, rules, has_formatter=formatter)


class SkipKinds(unittest.TestCase):
    def test_allow_listed_config_is_skipped(self):
        self.assertEqual(go(mod("config/a.json")), (SkipKind.CONFIG,))

    def test_a_100_percent_rename_is_skipped(self):
        self.assertEqual(go(DiffEntry(status="R", path="new/x.py", old="old/x.py")), (SkipKind.RENAME,))

    def test_a_formatter_only_change_is_skipped(self):
        self.assertEqual(go(mod("src/a.rs"), loud=()), (SkipKind.FORMATTER,))

    def test_formatter_only_needs_a_registered_formatter(self):
        self.assertEqual(go(mod("src/a.rs"), loud=(), formatter=False), ())

    def test_a_whitespace_change_in_python_is_not_formatter_only(self):
        self.assertEqual(go(mod("src/a.py"), loud=()), ())

    def test_generated_files_are_skipped(self):
        self.assertEqual(go(mod("gen/api.ts")), (SkipKind.GENERATED,))

    def test_tools_and_tests_only_are_skipped(self):
        self.assertEqual(go(mod("tools/x.py")), (SkipKind.TOOLS,))
        self.assertEqual(go(mod("tests/test_a.py"), DiffEntry(status="A", path="tests/b.py")), (SkipKind.TESTS,))

    def test_several_classes_give_each_reason_once(self):
        self.assertEqual(go(mod("config/a.json"), mod("gen/x"), mod("gen/y")), (SkipKind.CONFIG, SkipKind.GENERATED))


class CodeChangeMeansReview(unittest.TestCase):
    def test_one_code_path_among_mechanical_ones_is_reviewed(self):
        self.assertEqual(go(mod("config/a.json"), mod("tests/t.py"), mod("src/app.py")), ())

    def test_nothing_changed_is_reviewed(self):
        self.assertEqual(go(), ())

    def test_no_allow_list_skips_nothing_but_renames(self):
        self.assertEqual(go(mod("tests/t.py"), rules=ReviewSkipConfig()), ())

    def test_docs_and_markdown_are_never_skipped_whatever_the_list_says(self):
        wide = ReviewSkipConfig(config=["**"], tests=["**"])
        self.assertEqual(go(mod("docs/design.txt"), rules=wide), ())
        self.assertEqual(go(mod("README.md"), mod("tests/t.py"), rules=wide), ())
        self.assertEqual(go(DiffEntry(status="R", path="x.md", old="y.md"), rules=wide), ())

    def test_the_profile_itself_is_never_skipped(self):
        self.assertEqual(go(mod(".task-loop.json"), rules=ReviewSkipConfig(config=["*.json"])), ())

    def test_an_unknown_key_in_the_allow_list_is_refused(self):
        with self.assertRaises(config.ConfigError):
            config.load({"engine": {"skip_review": {"docs": ["**"]}}})
        self.assertEqual(config.load({"engine": {"skip_review": {"tests": ["t/**"]}}}).engine.skip_review.tests, ["t/**"])


if __name__ == "__main__":
    unittest.main()
