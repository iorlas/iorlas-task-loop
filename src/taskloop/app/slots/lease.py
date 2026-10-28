"""One Lease keeps beads' bd leases alive: the slot bead's and the task bead's from the slot take to the release (a slow slot
setup, lifesim 5-12 min, outlasts a 5-minute lease), and run-task's own (the bead, and the slot bead of a loop that started it).
Both a loop killed with SIGKILL and a run that outlives it then leave no slot free under a live run."""
import contextlib
import threading
from types import TracebackType
from typing import Self

from taskloop.contracts.ports import BdFailure, Beads

EVERY = 60.0  # seconds between beats; bd leases last 5 minutes


class Lease:
    def __init__(self, store: Beads, *ids: str | None, every: float = EVERY) -> None:
        self.store, self.every = store, every
        self.ids: list[str] = [i for i in ids if i]
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self) -> Self:
        self.thread.start()
        return self

    def add(self, bead_id: str) -> None:
        self.ids.append(bead_id)

    def drop(self, bead_id: str) -> None:
        if bead_id in self.ids:
            self.ids.remove(bead_id)

    def beat(self) -> None:
        for i in list(self.ids):
            with contextlib.suppress(BdFailure):  # a refused beat changes nothing: the next one tries again
                self.store.heartbeat(i)

    def run(self) -> None:
        while not self.stopped.wait(self.every):
            self.beat()

    def stop(self) -> None:
        self.stopped.set()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.stop()
