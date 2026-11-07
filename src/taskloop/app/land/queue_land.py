"""`tl land-stack` through the merge queue (docs/design/merge-queue.md 3): the items become queue entries, each gated on Q(N) at base
Q(N-1) up to `jobs` at once, and merged in order through `Stack.deliver`, which asserts the tested tree is the landed one. Dark: only a
`Stack(queue=True)` comes here, and anything the queue cannot judge (a PR already merged or closed, a profile change, one item) takes the
serial path unchanged."""
import threading
from typing import TYPE_CHECKING, final

from taskloop.app.land.cmds import Stop
from taskloop.app.land.queue_refs import QueueRefs
from taskloop.app.land.queue_run import QueueRun
from taskloop.contracts.forge import OPEN, StackItem
from taskloop.contracts.wire import Rec
from taskloop.domain.land.queue_model import Entry, Phase

if TYPE_CHECKING:
    from taskloop.app.land.stack import Stack


@final
class Queued(Rec):
    """What the queue gated for an item: head: the PR head, q: its queue commit Q(N), tree: T(N)."""

    head: str
    q: str
    tree: str


def queueable(stack: Stack, items: list[StackItem]) -> bool:
    """True when every item is an open PR (or a branch with none yet), nothing is a profile change, and there is a queue to speak of."""
    if len(items) < 2 or stack.profile_change is not None:
        return False
    try:
        return all(pr is None or pr.state == OPEN for _branch, _oid, pr in (stack.resolve(item) for item in items))
    except Stop:
        return False


class QueueLand:
    def __init__(self, stack: Stack) -> None:
        self.stack = stack
        self.items: dict[str, StackItem] = {}
        self.git_lock = threading.Lock()

    def run(self, items: list[StackItem]) -> None:
        stack = self.stack
        if not queueable(stack, items):
            for item in items:
                stack.item(item)
            return
        heads: list[tuple[str, str]] = []
        for item in items:
            branch, oid, _pr = stack.resolve(item)
            self.items[branch] = item
            heads.append((branch, oid))
        stack.forge.fetch()
        main = stack.git.rev_parse(stack.repo, stack.trees.main_ref)
        refs = QueueRefs(stack.cmds, stack.repo)
        queue = QueueRun(refs, self.gate, self.merge, in_flight=stack.jobs, main=main)
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
