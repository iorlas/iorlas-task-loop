"""The runner of the merge queue (docs/design/merge-queue.md section 3): it asks `plan` (domain/land/queue_model.py) what to do and does it
through three ports, so the queue is tested with fakes and wired to git, the gate and the forge in one place.

  refs   QueueRefs: make Q(N), drop a ref
  gate   (entry) -> bool: judge Q(N) in a fresh worktree; called on a thread, up to `in_flight` at a time
  merge  (entry, main) -> the new main: land the entry's PR (the tree assertion of app/land/treecheck.py lives behind it)

Merges happen on this thread, head first. A red gate or a conflict ejects its entry and stops the building and gating of the rest (the
repair of the entries behind it is bead tl-7s2f.5); what is already green still merges in order. The entries that left lose their refs."""
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Protocol

from taskloop.app.land.queue_refs import Conflict, Made
from taskloop.domain.land.queue_model import (
    Build,
    Built,
    Drop,
    Dropped,
    Ejected,
    Entry,
    Event,
    Gate,
    Gated,
    Landed,
    Merge,
    Phase,
    Started,
    apply,
    plan,
)


class Refs(Protocol):
    def make(self, n: int, parent: str, head: str) -> Made | Conflict: ...
    def drop(self, ref: str) -> None: ...


class QueueRun:
    def __init__(self, refs: Refs, gate: Callable[[Entry], bool], merge: Callable[[Entry, str], str], *, in_flight: int, main: str,
                 on_change: Callable[[Sequence[Entry]], None] = lambda _e: None) -> None:
        self.refs, self.gate, self.merge = refs, gate, merge
        self.in_flight, self.main = max(1, in_flight), main
        self.entries: list[Entry] = []
        self.on_change = on_change
        self.built = 0
        self.halted = False

    def see(self, event: Event) -> None:
        self.entries = apply(self.entries, event)
        self.on_change(self.entries)

    def by(self, branch: str) -> Entry:
        return next(e for e in self.entries if e.branch == branch)

    def build(self, act: Build) -> None:
        self.built += 1
        got = self.refs.make(self.built, act.parent, act.head)
        if isinstance(got, Conflict):
            self.see(Ejected(act.branch, f"conflict: {got.why}"))
            self.halted = True
        else:
            self.see(Built(act.branch, got.q, got.tree, got.ref))

    def land(self, act: Merge) -> None:
        self.main = self.merge(self.by(act.branch), self.main)
        self.see(Landed(act.branch))

    def settle(self, running: dict[Future[bool], str]) -> None:
        done, _ = wait(running, return_when=FIRST_COMPLETED)
        for fut in done:
            branch = running.pop(fut)
            green = fut.result()
            self.see(Gated(branch, green))
            self.halted = self.halted or not green

    def run(self, items: Sequence[tuple[str, str]]) -> list[Entry]:
        """Drive (branch, head) items to the end: merged, or ejected with a reason. -> the entries."""
        self.entries = [Entry(branch=b, head=h) for b, h in items]
        self.on_change(self.entries)
        running: dict[Future[bool], str] = {}
        with ThreadPoolExecutor(max_workers=self.in_flight) as pool:
            while True:
                moved = False
                for act in plan(self.entries, self.main, self.in_flight):
                    if isinstance(act, Drop):
                        self.refs.drop(act.ref)
                        self.see(Dropped(act.branch))
                        moved = True
                    elif isinstance(act, Merge):
                        self.land(act)
                        moved = True
                    elif isinstance(act, Build) and not self.halted:
                        self.build(act)
                        moved = True
                    elif isinstance(act, Gate) and not self.halted:
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
