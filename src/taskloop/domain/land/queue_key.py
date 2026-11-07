"""QueueKey: the identity of one build of the merge queue (docs/design/merge-queue.md section 4), one level above RunKey.

Two builds with equal keys are the same fact. `RunKey` stays the identity of one check's receipt; the key here says which queue state the
receipts were made for: the base, the heads ahead in order, the head, and the check set the profile at the base declares. A receipt crosses
from the queue parent to main only through Carry's `queue_parent` mode (app/land/carry.py)."""
import hashlib
from collections.abc import Iterable
from types import MappingProxyType
from typing import final

from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.contracts.wire import Rec

# The RunKey fields the profile at the base fixes: they make the check set. A field added to RunKey must be in one of these two tables
# (tests/land/test_queue_key.py), so a new input to a receipt cannot slip past the queue's key.
CHECK_SET_FIELDS = ("check", "cmd", "config", "toolchain", "env", "execution")
OTHER_FIELDS = MappingProxyType({
    "tree": "the tree T(N) of the build: reuse is by tree",
    "base": "QueueKey.base",
    "inputs": "what the check reads in the tree: follows from the tree",
    "selected": "the test set the tree and the base select: follows from them",
    "dependencies": "producer receipts consumed by one execution: a result of the build, not an input of it",
    "plan": "a planned skip of one execution: a result of the build",
    "plan_output": "a planned skip of one execution: a result of the build",
})


@final
class QueueKey(Rec):
    """base: the main sha the build started from. ahead: the heads of the PRs before this one, in queue order. head: this PR's head sha.
    check_set: check_set_hash of the gate's checks at the base."""

    base: BaseSha
    ahead: tuple[str, ...]
    head: str
    check_set: Digest


def check_set_hash(keys: Iterable[RunKey]) -> Digest:
    """A digest over the CHECK_SET_FIELDS of every check, whatever the order they come in."""
    rows = sorted("\0".join(str(getattr(k, f)) for f in CHECK_SET_FIELDS) for k in keys)
    return Digest(hashlib.sha1("\n".join(rows).encode()).hexdigest())
