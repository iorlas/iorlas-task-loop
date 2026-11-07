"""Is a bead visual: the planner's typed field decides, never a word list. A bead is visual iff some plan case is look-objective,
taste or show; only a visual bead runs the verify stage, any other lands with its unchecked items in one follow-up bead.
`visual_paths` is only a check on that judgement: a visual path touched with no such case sends the plan back to the planner once.
`unmet_shows` is the mechanical half of the `show` class: the named artifacts exist in the store for the current stage attempt.

Used by: plan, review, write.
"""
from collections.abc import Collection, Iterable, Sequence
from typing import Final

from taskloop.domain.work.matchers import word_set
from tlkernel.checkmatchers import glob_re
from tlkernel.plancheck import Open

VISUAL_CLASSES: Final = frozenset({"look-objective", "taste", "show"})


def is_visual(cases: Iterable[Open]) -> bool:
    return any(c.get("class", "test") in VISUAL_CLASSES for c in cases)


def touches_visual_path(paths: Sequence[str], include: Collection[str], exclude: Collection[str]) -> bool:
    return any(_hit(p, include) and not _hit(p, exclude) for p in paths)


def _hit(path: str, globs: Collection[str]) -> bool:
    return any(glob_re(g).match(path) for g in globs)


def unmet_shows(cases: Iterable[Open], have: Collection[tuple[str, str]]) -> list[str]:
    """The `show` items whose named artifacts are not all in `have` ((name, role) of the current stage attempt), one line each naming
    what is missing. A show case that names nothing asks for nothing checkable: it is not a miss."""
    out: list[str] = []
    for c in cases:
        if c.get("class", "test") != "show":
            continue
        lacking = [f"{r['name']} (role {r['role']})" for r in c.get("shows") or [] if (r["name"], r["role"]) not in have]
        if lacking:
            out.append(f"{c['criterion']}: missing {', '.join(lacking)}")
    return out


def names_criterion(what: str, acceptance: str) -> bool:
    """True when an unchecked item is about one acceptance line of the bead: at least four words of the item (half of them) stand in one
    line. Such an item is the owner's to decide, so it is asked, never filed as a follow-up."""
    mine = word_set(what)
    need = max(4, int(0.5 * len(mine)))
    return len(mine) >= 4 and any(len(mine & word_set(line)) >= need for line in acceptance.splitlines() if line.strip())
