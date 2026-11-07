"""The durable merge queue document, replaced by its runner once per change."""
from typing import ClassVar

import msgspec

from tlkernel.wire import Rec


class BuildRow(Rec):
    pid: int
    start_id: str
    lease_expires: float
    worktree: str


class EntryRow(Rec):
    branch: str = ""
    head: str = ""
    phase: str = ""
    q: str = ""
    tree: str = ""
    ref: str = ""
    reason: str = ""
    base: str = ""
    ahead: list[str] = msgspec.field(default_factory=list)
    check_set: str = ""
    build: BuildRow | None = None


class QueueDoc(Rec):
    V: ClassVar[int] = 1
    entries: list[EntryRow] = msgspec.field(default_factory=list)
    in_flight: int = 1
    last_base: str = ""
