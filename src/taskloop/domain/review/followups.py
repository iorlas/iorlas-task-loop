"""The follow-up beads the engine files for a run: which are new, which are too many. A follow-up is one thing, named by a typed key
(source bead, finding category, file), never by its title; a run files at most FOLLOW_UP_CAP of them, the rest go in one comment."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

FOLLOW_UP_CAP: Final = 3


@dataclass(frozen=True)
class FollowKey:
    """What makes two follow-ups the same. A leftover that names no file (a plan's, a review's free text) is its own subject: its title."""

    bead: str
    category: str
    file: str

    @classmethod
    def of(cls, bead: str, lo: Mapping[str, str]) -> "FollowKey":
        return cls(bead, lo.get("category") or "leftover", lo.get("file") or lo["title"])

    def __str__(self) -> str:
        return f"{self.bead}|{self.category}|{self.file}"


def label(bead: str, round_no: int) -> str:
    """The one label a filed follow-up carries: where it came from."""
    return f"from:{bead}-r{round_no}"


@dataclass(frozen=True)
class Batch:
    file: list[Mapping[str, str]]
    over: list[Mapping[str, str]]


def batch(bead: str, leftovers: Sequence[Mapping[str, str]], filed: Sequence[str]) -> Batch:
    """The leftovers not yet filed (`filed`: the keys of the filed ones), one per key; the first CAP minus those filed already are to be
    filed, the others are over."""
    todo: dict[str, Mapping[str, str]] = {}
    for lo in leftovers:
        key = str(FollowKey.of(bead, lo))
        if key not in filed:
            todo.setdefault(key, lo)
    room = max(FOLLOW_UP_CAP - len(filed), 0)
    rows = list(todo.values())
    return Batch(rows[:room], rows[room:])
