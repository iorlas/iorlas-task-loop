"""`tl land-stack` through the merge queue (docs/design/merge-queue.md 3): the items become queue entries, each gated on Q(N) at base
Q(N-1) up to `jobs` at once, and merged in order through `Stack.deliver`, which asserts the tested tree is the landed one. Dark: only a
`Stack(queue=True)` comes here, and anything the queue cannot judge (a PR already merged or closed, a profile change, one item) takes the
serial path unchanged."""
import threading
import time
from collections.abc import Callable
from typing import Protocol, final

from tlkernel.beadsport import Beads
from tlkernel.forge import OPEN, Pr, StackItem
from tlkernel.gitport import Git
from tlkernel.queue_doc import QueueDoc
from tlkernel.wire import Rec, Refused

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.queue import InFlight
from taskloop.app.land.queue_enqueue import enqueue
from taskloop.app.land.queue_recover import recover
from taskloop.app.land.queue_refs import QueueRefs
from taskloop.app.land.queue_run import QueueRun
from taskloop.app.land.stackgate import StackGate
from taskloop.app.land.treecheck import TreeGuard
from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_persist import to_doc
from taskloop.stores.api import Doc
from taskloop.stores.runlog import RunLog


@final
class Queued(Rec):
    """What the queue gated for an item: head: the PR head, q: its queue commit Q(N), tree: T(N)."""

    head: str
    q: str
    tree: str


class Host(Protocol):
    """What the queue asks of the `Stack` that runs it (Stack imports this module, so it cannot be named here)."""

    profile_change: str | None
    jobs: int
    repo: str
    last: str
    cmds: Cmds
    git: Git
    beads: Beads
    forge: Forge
    gate: StackGate
    trees: TreeGuard
    log: RunLog
    record: Callable[[str, str], int]

    @property
    def queue_doc(self) -> Doc[QueueDoc]: ...

    def resolve(self, item: StackItem) -> tuple[str, str, Pr | None]: ...
    def item(self, item: StackItem) -> None: ...
    def deliver(self, item: StackItem, queued: Queued | None = None) -> None: ...


def queueable(stack: Host, items: list[StackItem]) -> bool:
    """True when every item is an open PR (or a branch with none yet), nothing is a profile change, and there is a queue to speak of."""
    if len(items) < 2 or stack.profile_change is not None:
        return False
    try:
        return all(pr is None or pr.state == OPEN for _branch, _oid, pr in (stack.resolve(item) for item in items))
    except Stop:
        return False


class QueueLand:
    def __init__(self, stack: Host) -> None:
        self.stack = stack
        self.items: dict[str, StackItem] = {}
        self.git_lock = threading.Lock()

    def run(self, items: list[StackItem]) -> None:
        stack = self.stack
        doc = stack.queue_doc
        try:
            stale = doc.need()  # a queue document of another version or a torn one is refused, never read as no queue
        except Refused as e:
            raise Stop(1, f"queue: {e}") from None
        if stale is not None:
            recover(stack, stale, time.time())
        if not queueable(stack, items):
            for item in items:
                stack.item(item)
            return
        heads: list[tuple[str, str]] = []
        for item in items:
            branch, oid, _pr = stack.resolve(item)
            self.items[branch] = item
            heads.append((branch, oid))
        beads_of = {branch: item.bead or (branch.removeprefix("task/") if branch.startswith("task/") else "")
                    for branch, item in self.items.items()}
        cap = enqueue(stack, heads, beads_of)
        flight = InFlight(cap=1 if cap == 1 else stack.jobs)
        flight.current = min(flight.cap, max(1, stale.in_flight)) if stale is not None else 1
        stack.forge.fetch()
        main = stack.git.rev_parse(stack.repo, stack.trees.main_ref)
        refs = QueueRefs(stack.cmds, stack.repo)
        queue = QueueRun(refs, self.gate, self.merge, flight=flight, main=main,
                         on_change=lambda entries: doc.write(to_doc(entries, {}, in_flight=flight.current, last_base=main)))
        try:
            entries = queue.run(heads)
        finally:
            for e in queue.entries:
                if e.ref:
                    refs.drop(e.ref)
        self.report(entries)

    def gate(self, entry: Entry) -> bool:
        with self.git_lock:
            parent = self.stack.git.rev_parse(self.stack.repo, f"{entry.q}^")
        return self.stack.gate.judge_queue(entry.q, parent, self.git_lock)

    def merge(self, entry: Entry, _main: str) -> str:
        self.stack.deliver(self.items[entry.branch], queued=Queued(head=entry.head, q=entry.q, tree=entry.tree))
        return self.stack.last

    @staticmethod
    def report(entries: list[Entry]) -> None:
        merged = sum(e.phase is Phase.MERGED for e in entries)
        left = [e for e in entries if e.phase not in (Phase.MERGED, Phase.EJECTED)]
        for e in entries:
            if e.phase is Phase.EJECTED:
                raise Stop(1, f"queue: {e.branch} ejected ({e.reason}); {merged} merged, {len(entries) - merged - 1} left untouched")
        if left:
            raise Stop(1, f"queue: {len(left)} left unmerged after {merged} merged")
