"""One sink for stage follow-ups, reading the run's current list after checkpoint rebindings."""
from collections.abc import Sequence
from typing import Protocol

from tlkernel.wire import Open

from taskloop.domain.followups import FollowKey


class LeftoverFields(Protocol):
    leftovers: list[Open]


class LeftoverQueue:
    def __init__(self, fields: LeftoverFields) -> None:
        self.fields = fields

    def add_titled(self, lo: Open) -> bool:
        if lo["title"] in {x["title"] for x in self.fields.leftovers}:
            return False
        self.fields.leftovers.append(lo)
        return True

    def add_keyed(self, bead: str, lo: Open) -> bool:
        if FollowKey.of(bead, lo) in {FollowKey.of(bead, x) for x in self.fields.leftovers}:
            return False
        self.fields.leftovers.append(lo)
        return True

    def extend(self, items: Sequence[Open]) -> None:
        self.fields.leftovers.extend(items)
