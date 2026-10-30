"""RunKey: the identity of one run of a check. Two runs with equal keys are the same fact, so the second is never made: the memo
(app/checks/cache.py) holds the green results by this key, and the land gate asks it, not a second copy of the decision."""
from typing import NewType, final

from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.wire import Rec

BaseSha = NewType("BaseSha", str)  # a commit sha of the base branch: never a tree hash
Digest = NewType("Digest", str)  # a sha1 hex of what a check reads (`inputs`) or of the environment it runs in (`env`)


@final
class RunKey(Rec):
    """check: the check's id. tree: the hash of the worktree, "" when `inputs` says what the check reads instead. base: the base
    sha, "" when the check says `inputs_only`. inputs: the command and the files it reads. env: what the engine hands the child."""

    check: CheckId
    tree: TreeSha
    base: BaseSha
    inputs: Digest
    env: Digest
