"""A recording admission host for tests: one in-memory store, an area lock that fails if taken twice, and an event trail."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tltestkit.membeads import MemBeads


@dataclass
class FakeAreasHost:
    configured: bool = True
    events: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    occupancy: dict[BeadId, str] = field(default_factory=dict)
    reads: list[tuple[MemBeads, BeadId]] = field(default_factory=list)
    locked: bool = False
    store: MemBeads = field(default_factory=MemBeads)
    areas: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for bid in ("x-1", "x-2"):
            self.store.put(Bead(id=BeadId(bid), title="", status="open", labels=["lane:live"]))

    @property
    def area_label_prefix(self) -> str:
        return "lane:" if self.configured else ""

    @property
    def say(self) -> Callable[[str], None]:
        return self.said.append

    @contextmanager
    def area_lock(self) -> Iterator[None]:
        assert not self.locked
        self.locked = True
        self.events.append("lock")
        try:
            yield
        finally:
            self.events.append("unlock")
            self.locked = False

    def running(self) -> dict[BeadId, str]:
        assert self.locked
        self.events.append("refresh")
        return self.occupancy

    def step[T](self, name: str, result: T) -> T:
        self.events.append(name)
        return result
