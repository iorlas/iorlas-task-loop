"""One Lease keeps beads' bd leases alive: the slot bead's and the task bead's from the slot take to the release (a slow slot
setup, 5-12 min on a large consumer, outlasts a 5-minute lease), and run-task's own (the bead, and the slot bead of a loop that started it).
Both a loop killed with SIGKILL and a run that outlives it then leave no slot free under a live run."""
import contextlib
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Self

from tlkernel.beadsport import BdFailure, Beads
from tlkernel.ids import BeadId
from tlkernel.runlife import BEAT_EVERY, JOIN_WAIT

EVERY = BEAT_EVERY  # seconds between beats; bd leases last 5 minutes


class Lease:
    def __init__(self, store: Beads, *ids: BeadId | None, every: float = EVERY, on_beat: Callable[[], None] | None = None,
                 on_death: Callable[[BaseException], None] | None = None) -> None:
        self.store, self.every, self.on_beat, self.on_death = store, every, on_beat, on_death
        self.died: BaseException | None = None
        self.ids: list[BeadId] = [i for i in ids if i]
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self) -> Self:
        self.thread.start()
        return self

    def add(self, bead_id: BeadId) -> None:
        self.ids.append(bead_id)

    def drop(self, bead_id: BeadId) -> None:
        if bead_id in self.ids:
            self.ids.remove(bead_id)

    def beat(self) -> None:
        for i in list(self.ids):
            with contextlib.suppress(BdFailure):  # a refused beat changes nothing: the next one tries again
                self.store.heartbeat(i)
        if self.on_beat is not None:
            self.on_beat()

    def run(self) -> None:
        """The beat loop; an error out of a beat ends it, and the death is kept (`died`) and told to `on_death`, not lost."""
        try:
            while not self.stopped.wait(self.every):
                self.beat()
        except Exception as err:
            self.died = err
            if self.on_death is not None:
                with contextlib.suppress(Exception):
                    self.on_death(err)

    def stop(self) -> None:
        """Ends the beats and waits out a beat in flight: a thread left running past this call uses stores its owner is about to close."""
        self.stopped.set()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(JOIN_WAIT)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.stop()
