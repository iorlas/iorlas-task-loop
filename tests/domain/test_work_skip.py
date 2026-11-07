"""domain/work/skip.py: a stage's review is skipped only when every changed path is mechanical; one other path means review."""
import sys
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.work.skip import SkipKind, decide
from tlkernel import config
from tlkernel.config import ReviewSkipConfig
from tlkernel.gitfacts import DiffEntry

RULES = ReviewSkipConfig(config=["config/*.json"], generated=["gen/**"], tools=["tools/**"], tests=["tests/**"])


def mod(path: str) -> DiffEntry:
    return DiffEntry(status="M", path=path)


def go(*entries: DiffEntry, loud: tuple[str, ...] | None = None, formatter: bool = True, rules: ReviewSkipConfig = RULES,
       maps_acceptance: bool = False):
    significant = frozenset(e.path for e in entries) if loud is None else frozenset(loud)
    return decide(list(entries), significant, rules, has_formatter=formatter, maps_acceptance=maps_acceptance)


class SkipKinds(Case):
    def test_allow_listed_config_is_skipped(self):
        assert go(mod("config/a.json")) == (SkipKind.CONFIG,)

    def test_a_100_percent_rename_is_skipped(self):
        assert go(DiffEntry(status="R", path="new/x.py", old="old/x.py")) == (SkipKind.RENAME,)

    def test_a_formatter_only_change_is_skipped(self):
        assert go(mod("src/a.rs"), loud=()) == (SkipKind.FORMATTER,)

    def test_formatter_only_needs_a_registered_formatter(self):
        assert go(mod("src/a.rs"), loud=(), formatter=False) == ()

    def test_a_whitespace_change_in_python_is_not_formatter_only(self):
        assert go(mod("src/a.py"), loud=()) == ()

    def test_generated_files_are_skipped(self):
        assert go(mod("gen/api.ts")) == (SkipKind.GENERATED,)

    def test_tools_and_tests_only_are_skipped(self):
        assert go(mod("tools/x.py")) == (SkipKind.TOOLS,)
        assert go(mod("tests/test_a.py"), DiffEntry(status="A", path="tests/b.py")) == (SkipKind.TESTS,)

    def test_several_classes_give_each_reason_once(self):
        assert go(mod("config/a.json"), mod("gen/x"), mod("gen/y")) == (SkipKind.CONFIG, SkipKind.GENERATED)


class CodeChangeMeansReview(Case):
    def test_one_code_path_among_mechanical_ones_is_reviewed(self):
        assert go(mod("config/a.json"), mod("tests/t.py"), mod("src/app.py")) == ()

    def test_the_stage_that_maps_the_acceptance_is_reviewed_whatever_its_paths(self):
        assert go(mod("tests/t.py"), maps_acceptance=True) == ()
        assert go(DiffEntry(status="R", path="b", old="a"), maps_acceptance=True) == ()

    def test_nothing_changed_is_reviewed(self):
        assert go() == ()

    def test_no_allow_list_skips_nothing_but_renames(self):
        assert go(mod("tests/t.py"), rules=ReviewSkipConfig()) == ()

    def test_docs_and_markdown_are_never_skipped_whatever_the_list_says(self):
        wide = ReviewSkipConfig(config=["**"], tests=["**"])
        assert go(mod("docs/design.txt"), rules=wide) == ()
        assert go(mod("README.md"), mod("tests/t.py"), rules=wide) == ()
        assert go(DiffEntry(status="R", path="x.md", old="y.md"), rules=wide) == ()

    def test_the_profile_itself_is_never_skipped(self):
        assert go(mod(".task-loop.json"), rules=ReviewSkipConfig(config=["*.json"])) == ()

    def test_an_unknown_key_in_the_allow_list_is_refused(self):
        with pytest.raises(config.ConfigError):
            config.load({"engine": {"skip_review": {"docs": ["**"]}}})
        assert config.load({"engine": {"skip_review": {"tests": ["t/**"]}}}).engine.skip_review.tests == ["t/**"]
