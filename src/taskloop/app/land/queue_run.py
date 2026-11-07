"""The runner of the merge queue (docs/design/merge-queue.md section 3): it asks `plan` (domain/land/queue_model.py) what to do and does it
through three ports, so the queue is tested with fakes and wired to git, the gate and the forge in one place.

  refs   QueueRefs: make Q(N), drop a ref
  gate   (entry) -> bool: judge Q(N) in a fresh worktree; called on a thread, up to `in_flight` at a time
  merge  (entry, main) -> the new main: land the entry's PR (the tree assertion of app/land/treecheck.py lives behind it)

Merges happen on this thread, head first. Attribution ejects culprits and rebuilds only entries behind them.
Invalidated futures are discarded. Running gates cannot yet be killed: process-group cancellation needs a spawner cancel API
in a follow-up. Entries that left lose their refs."""
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Protocol

from taskloop.app.land.queue import InFlight
from taskloop.app.land.queue_refs import Conflict, Made
from taskloop.domain.land.queue_in_flight import Cause
from taskloop.domain.land.queue_in_flight import Event as FlightEvent
from taskloop.domain.land.queue_model import (
    Build,
    Built,
    Drop,
    Dropped,
    Eject,
    Ejected,
    Entry,
    Event,
    Gate,
    Gated,
    Landed,
    Merge,
    Phase,
    Reset,
    Started,
    apply,
    plan,
)


class Refs(Protocol):
    def make(self, n: int, parent: str, head: str) -> Made | Conflict: ...
    def drop(self, ref: str) -> None: ...


class QueueRun:
    def __init__(self, refs: Refs, gate: Callable[[Entry], bool], merge: Callable[[Entry, str], str], *, flight: InFlight, main: str,
                 on_change: Callable[[Sequence[Entry]], None] = lambda _e: None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.refs, self.gate, self.merge = refs, gate, merge
        self.flight, self.main = flight, main
        self.clock = clock
        self.started: dict[str, float] = {}
        self.gate_s: dict[str, float] = {}
        self.entries: list[Entry] = []
        self.on_change = on_change
        self.built = 0
        self.doomed: set[Future[bool]] = set()

    def see(self, event: Event) -> None:
        self.entries = apply(self.entries, event)
        self.on_change(self.entries)

    def by(self, branch: str) -> Entry:
        return next(e for e in self.entries if e.branch == branch)

    def build(self, act: Build) -> None:
        self.built += 1
        got = self.refs.make(self.built, act.parent, act.head)
        if isinstance(got, Conflict):
            self.flight.happened(FlightEvent.CONFLICT_EJECT)
            self.see(Ejected(act.branch, f"conflict: {got.why}"))
        else:
            self.see(Built(act.branch, got.q, got.tree, got.ref, act.after))

    def land(self, act: Merge) -> None:
        self.main = self.merge(self.by(act.branch), self.main)
        self.flight.merged(len(self.merged()) + 1, self.gate_s.pop(act.branch, 0.0))
        self.see(Landed(act.branch))

    def settle(self, running: dict[Future[bool], str]) -> None:
        done, _ = wait(running, return_when=FIRST_COMPLETED)
        for fut in done:
            branch = running.pop(fut)
            if fut in self.doomed:
                self.doomed.remove(fut)
                continue
            green = fut.result()
            started = self.started.pop(branch, None)
            self.gate_s[branch] = self.clock() - started if started is not None else 0.0
            self.see(Gated(branch, green))

    def reset(self, act: Reset, running: dict[Future[bool], str]) -> None:
        for fut, branch in running.items():
            if branch == act.branch and fut not in self.doomed:
                self.doomed.add(fut)
                fut.cancel()
                self.flight.waste(self.clock() - self.started.pop(branch, self.clock()), Cause.CULPRIT_AHEAD)
        if act.branch in self.gate_s:
            self.flight.waste(self.gate_s.pop(act.branch), Cause.CULPRIT_AHEAD)
        self.refs.drop(act.ref)
        self.see(Reset(act.branch))

    def run(self, items: Sequence[tuple[str, str]]) -> list[Entry]:
        """Drive (branch, head) items to the end: merged, or ejected with a reason. -> the entries."""
        self.entries = [Entry(branch=b, head=h) for b, h in items]
        self.on_change(self.entries)
        running: dict[Future[bool], str] = {}
        with ThreadPoolExecutor(max_workers=self.flight.cap) as pool:
            while True:
                moved = False
                for act in plan(self.entries, self.main, self.flight.current):
                    if isinstance(act, Drop):
                        self.refs.drop(act.ref)
                        self.see(Dropped(act.branch))
                        moved = True
                    elif isinstance(act, Eject):
                        self.flight.happened(FlightEvent.GATE_FAILED)
                        self.see(Ejected(act.branch, act.reason))
                        moved = True
                    elif isinstance(act, Reset):
                        self.reset(act, running)
                        moved = True
                    elif isinstance(act, Merge):
                        self.land(act)
                        moved = True
                    elif isinstance(act, Build):
                        self.build(act)
                        moved = True
                    elif isinstance(act, Gate):
                        self.started[act.branch] = self.clock()
                        running[pool.submit(self.gate, self.by(act.branch))] = act.branch
                        self.see(Started(act.branch))
                        moved = True
                if running and not moved:
                    self.settle(running)
                elif not moved:
                    break
        return self.entries

    def merged(self) -> list[str]:
        return [e.branch for e in self.entries if e.phase is Phase.MERGED]
