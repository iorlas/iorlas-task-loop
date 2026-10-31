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
    def of(cls, bead: str, lo: Mapping[str, str]) -> FollowKey:
        return cls(bead, lo.get("category") or "leftover", lo.get("file") or lo["title"])

    def __str__(self) -> str:
        return f"{self.bead}|{self.category}|{self.file}"


def label(bead: str, round_no: int) -> str:
    """The one label a filed follow-up carries: where it came from."""
    return f"from:{bead}-r{round_no}"


UNCHECKED: Final = "unchecked"  # the category of the one follow-up that carries what a non-visual bead landed without verifying
TAG: Final = "follow-up"


NOT_VISUAL: Final = "is not a visual bead, so verify did not run"
REVIEW_OFF: Final = "is a visual bead but engine.review is off, so verify and look were skipped (no reviewer-role call)"


def unchecked(bead: str, items: Sequence[Mapping[str, str]], cause: str = NOT_VISUAL) -> dict[str, str]:
    """The leftover for a non-visual bead's unchecked items: one per bead (its key is (bead, UNCHECKED, "verify")), so a rerun that
    adds it again files nothing new."""
    rows = "\n".join(f"- {u['what']} ({u['kind']})" + (f": {u['why']}" if u.get("why") else "") for u in items)
    return {"title": f"{title_prefix(bead)} {len(items)} item(s) nobody verified", "category": UNCHECKED, "file": "verify",
            "why": f"{bead} {cause}; it landed with these unchecked items:\n{rows}"}


def title_prefix(bead: str) -> str:
    return f"Check after landing {bead}:"


def labels(bead: str, round_no: int, lo: Mapping[str, str]) -> list[str]:
    """The labels of a follow-up: where it came from, and the tag the unchecked-items follow-up carries."""
    return [label(bead, round_no), *([TAG] if lo.get("category") == UNCHECKED else [])]


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
    room = max(FOLLOW_UP_CAP - sum(f.split("|")[1:2] != [UNCHECKED] for f in filed), 0)  # the unchecked follow-up is outside the cap
    own = [lo for lo in todo.values() if lo.get("category") == UNCHECKED]
    rows = [lo for lo in todo.values() if lo.get("category") != UNCHECKED]
    return Batch([*own, *rows[:room]], rows[room:])
