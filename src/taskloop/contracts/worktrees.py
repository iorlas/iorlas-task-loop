"""The ownership record of a worktree tl made (worktrees/<repo key>/<name>-<hash>.json under the config dir): who made it and why."""
from typing import final

from taskloop.contracts.wire import Rec


@final
class Owned(Rec):
    """kind: "slot" or "loop". run: the session that made it (a run id when a run did). bead: the bead it was made for, "" when none."""

    path: str
    repo: str
    kind: str
    run: str
    host: str
    created: float
    bead: str = ""
