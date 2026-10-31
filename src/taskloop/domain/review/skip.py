"""When a stage's review is skipped: a pure rule over the stage's diff, never a model call. Every changed path must be mechanical (a
100% rename, a formatter-only change, or a path the profile allow-lists as config, generated, tools or tests); one other path, an empty
diff or any doubt means the review runs. Docs and markdown and the profile itself are never skipped."""
from collections.abc import Collection, Sequence
from enum import StrEnum
from typing import Final

from taskloop.contracts.config import ReviewSkipConfig
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.domain.checks.matchers import glob_re

NEVER: Final = ("**/*.md", "**/*.mdx", "**/*.rst", "docs/**", ".task-loop.json")  # always reviewed, whatever the lists say
INDENTED: Final = (".py", ".pyi", ".yaml", ".yml", ".mk", ".nim", ".haml", ".slim", ".coffee", ".pug", ".jade", ".sass", ".styl")
INDENTED_NAMES: Final = ("Makefile", "makefile", "GNUmakefile", "Justfile", "justfile")  # whitespace is syntax there: not formatter-only


class SkipKind(StrEnum):
    """Why a stage's review was skipped: one per class of mechanical path."""
    CONFIG = "config"
    RENAME = "rename"
    FORMATTER = "formatter"
    GENERATED = "generated"
    TOOLS = "tools"
    TESTS = "tests"
    REVIEW_OFF = "review-off"  # engine.review off (or the bead's label): not a path class, the whole review is switched off
    REVIEW_SAMPLED = "review-sampled"  # engine.review sampled: this stage is not the Nth


def _hit(path: str, globs: Collection[str]) -> bool:
    return any(glob_re(g).match(path) for g in globs)


def _whitespace_syntax(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in INDENTED_NAMES or name.endswith(INDENTED)


def _kind(e: DiffEntry, quiet: bool, rules: ReviewSkipConfig, has_formatter: bool) -> SkipKind | None:
    paths = [e.path, *([e.old] if e.old else [])]
    if any(_hit(p, NEVER) for p in paths):
        return None
    if e.status == "R":
        return SkipKind.RENAME
    for kind, globs in ((SkipKind.CONFIG, rules.config), (SkipKind.GENERATED, rules.generated), (SkipKind.TOOLS, rules.tools),
                        (SkipKind.TESTS, rules.tests)):
        if _hit(e.path, globs):
            return kind
    if e.status == "M" and quiet and has_formatter and not _whitespace_syntax(e.path):
        return SkipKind.FORMATTER
    return None


def decide(entries: Sequence[DiffEntry], significant: Collection[str], rules: ReviewSkipConfig, *,
           has_formatter: bool, maps_acceptance: bool) -> tuple[SkipKind, ...]:
    """The reasons the review is skipped (each kind once, in enum order), or () when it runs. `entries` is the stage's whole diff with
    exact renames; `significant` the paths that still differ when whitespace is ignored; `has_formatter` that the repo registers a
    formatter (a check with a fix command), which has already run over this tree. The stage that maps the bead's acceptance
    (`maps_acceptance`) is always reviewed: nobody else checks the acceptance."""
    if maps_acceptance or not entries:
        return ()
    kinds = {_kind(e, e.path not in significant, rules, has_formatter) for e in entries}
    if None in kinds:
        return ()
    return tuple(k for k in SkipKind if k in kinds)
