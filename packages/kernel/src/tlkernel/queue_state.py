"""What the merge queue's tree assertion leaves behind, one document per repo: the incidents it found and whether it froze the queue.

A frozen queue merges nothing and starts no gate until the owner (or the repair of docs/design/merge-queue.md section 2.1) clears it."""
from typing import ClassVar

import msgspec

from tlkernel.wire import Rec

RACED = "raced"  # the parent of the merge commit is not the main the gate assumed: someone else pushed to main in between
CORRUPT = "corrupt"  # the parent is as expected and the tree is not the tested one


class Incident(Rec):
    t: float
    kind: str
    pr: int
    bead: str
    main_before: str
    merge_sha: str
    parent: str
    expected_tree: str
    landed_tree: str


class QueueState(Rec):
    V: ClassVar[int] = 1
    frozen: bool = False
    incidents: list[Incident] = msgspec.field(default_factory=list)
