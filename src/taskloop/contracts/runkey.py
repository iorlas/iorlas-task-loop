"""RunKey: the identity of one run of a check. Two runs with equal keys are the same fact, so the second is never made: the result store
(app/checks/cache.py) holds the green results by this key, and the land gate asks it, not a second copy of the decision."""
from typing import NewType, final

from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.wire import Rec

BaseSha = NewType("BaseSha", str)  # a commit sha of the base branch: never a tree hash
Digest = NewType("Digest", str)  # a sha1 hex of what a check reads (`inputs`) or of the environment it runs in (`env`)


@final
class RunKey(Rec):
    """check: the check's id. cmd: the command. config: the check's declared settings that change what it reads or how it runs.
    toolchain: the host and the toolchain pins of the tree. tree: the hash of the worktree, "" when `inputs` says what the check
    reads instead. base: the base sha, "" when the check says `inputs_only`. inputs: the files it reads. selected: the resolved test
    set it runs ("" when it runs all). env: what the engine hands the child."""

    check: CheckId
    cmd: Digest
    config: Digest
    toolchain: Digest
    tree: TreeSha
    base: BaseSha
    inputs: Digest
    selected: Digest
    env: Digest
