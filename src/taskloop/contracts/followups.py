"""Pending follow-ups belong to the bead, beyond the lifetime of a run's checkpoint."""
from typing import ClassVar

import msgspec

from taskloop.contracts.wire import Rec


class FollowupOutbox(Rec):
    V: ClassVar[int] = 1
    pending: list[dict[str, str]] = msgspec.field(default_factory=list)
