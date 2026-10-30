"""Is a bead visual: a pure decision over typed facts, never a model call. Only a visual bead runs the verify stage; any other lands
with its unchecked items in one follow-up bead. Any doubt (no file known, or a file of a kind this table does not know
when the profile declares no visual paths) counts as visual, so it is verified."""
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from taskloop.domain.checks.matchers import glob_re
from taskloop.domain.plan.matchers import word_set
from taskloop.domain.review.matchers import VisualWords

FOLLOW_UP_LABEL: Final = "follow-up"
PLAIN_EXT: Final = frozenset({
    ".py", ".pyi", ".rs", ".go", ".java", ".kt", ".rb", ".sh", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".sql", ".lua", ".gd",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock", ".md", ".rst", ".txt", ".csv", ".gitignore", ".asmdef", ".meta"})
PLAIN_NAMES: Final = frozenset({"Makefile", "makefile", "Justfile", "justfile", "Dockerfile", "LICENSE", "CODEOWNERS"})


class VisualWhy(StrEnum):
    """Why a bead counts as visual: one per fact that said so."""
    PATHS = "visual_paths"
    EVIDENCE = "evidence"
    LABEL = "label"
    STAGE = "stage"
    LOOK = "look"
    DOUBT = "doubt"


@dataclass(frozen=True)
class VisualFacts:
    """What the decision reads: the files the stages name and the diff touched, the bead's labels and acceptance, the stage goals, the
    profile's visual globs, and whether a gap is a look item."""
    paths: Sequence[str]
    labels: Sequence[str]
    acceptance: str
    goals: Sequence[str]
    include: Collection[str]
    exclude: Collection[str]
    look_item: bool


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name in PLAIN_NAMES:
        return ".txt"
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else "?"


def _hit(path: str, globs: Collection[str]) -> bool:
    return any(glob_re(g).match(path) for g in globs)


def why(f: VisualFacts) -> tuple[VisualWhy, ...]:
    """The reasons the bead is visual (each once, in enum order), or () when it is not."""
    out: set[VisualWhy] = set()
    if f.look_item:
        out.add(VisualWhy.LOOK)
    if any(_hit(p, f.include) and not _hit(p, f.exclude) for p in f.paths):
        out.add(VisualWhy.PATHS)
    if any(VisualWords.in_label(x) for x in f.labels):
        out.add(VisualWhy.LABEL)
    if VisualWords.in_text(f.acceptance):
        out.add(VisualWhy.EVIDENCE)
    if any(VisualWords.in_text(g) for g in f.goals):
        out.add(VisualWhy.STAGE)
    if not f.paths:
        out.add(VisualWhy.DOUBT)
    elif not f.include and any(_ext(p) not in PLAIN_EXT for p in f.paths):
        out.add(VisualWhy.DOUBT)  # no declared visual paths: a file kind this table does not know may be a picture
    return tuple(k for k in VisualWhy if k in out)


def is_visual(f: VisualFacts) -> bool:
    return bool(why(f))


def names_criterion(what: str, acceptance: str) -> bool:
    """True when an unchecked item is about one acceptance line of the bead: at least four words of the item (half of them) stand in one
    line. Such an item is the owner's to decide, so it is asked, never filed as a follow-up."""
    mine = word_set(what)
    need = max(4, int(0.5 * len(mine)))
    return len(mine) >= 4 and any(len(mine & word_set(line)) >= need for line in acceptance.splitlines() if line.strip())
