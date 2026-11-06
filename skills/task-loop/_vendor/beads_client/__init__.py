"""beads-client: a lean, typed, fail-loud client over the bd CLI. Stdlib only; imports no host."""

from beads_client.client import TESTED_BELOW, TESTED_FROM, Bd, SyncResult
from beads_client.errors import BdError, ErrorKind
from beads_client.records import Bead, Comment, Dep, NewBead
from beads_client.runner import BdRun, Runner, subprocess_runner

__all__ = [
    "TESTED_BELOW",
    "TESTED_FROM",
    "Bd",
    "BdError",
    "BdRun",
    "Bead",
    "Comment",
    "Dep",
    "ErrorKind",
    "NewBead",
    "Runner",
    "SyncResult",
    "subprocess_runner",
]
