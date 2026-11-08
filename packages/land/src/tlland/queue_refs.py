"""The queue refs of the merge queue (docs/design/merge-queue.md 3.2): Q(N) is a commit with the tree `git merge-tree --write-tree Q(N-1)
head(N)` made, parent Q(N-1), kept under refs/tl/queue/<n>-<short head>. Local only, never pushed, deleted when the entry leaves the
queue. A conflict is a result (`Conflict`), not an exception. Every git call is a row of the run (Cmds)."""
from typing import final

from tlkernel.wire import Rec

from tlland.cmds import Cmds, Stop

PREFIX = "refs/tl/queue/"


@final
class Made(Rec):
    q: str
    tree: str
    ref: str


@final
class Conflict(Rec):
    why: str


class QueueRefs:
    def __init__(self, cmds: Cmds, repo: str) -> None:
        self.cmds, self.repo = cmds, repo

    def git(self, *argv: str) -> str:
        """git's stdout; a failing call stops the run (a queue that cannot write its refs has nothing to stand on)."""
        # git-port-exempt: merge-tree, commit-tree and update-ref have no Git port method; a port waits for a second caller
        ran = self.cmds.run(["git", *argv], cwd=self.repo)
        if ran.exit:
            raise Stop(1, f"git {' '.join(argv[:2])} failed (exit {ran.exit}): {ran.err.strip()[:200]}")
        return ran.out.strip()

    def make(self, n: int, parent: str, head: str) -> Made | Conflict:
        """Q(n) of `head` on `parent`, or the conflict that keeps `head` out of the queue."""
        merged = self.cmds.run(["git", "merge-tree", "--write-tree", parent, head], cwd=self.repo)
        if merged.exit == 1:
            lines = [ln for ln in merged.out.splitlines() if ln.startswith("CONFLICT")]
            return Conflict(why="; ".join(lines[:3]) or "merge-tree reported a conflict")
        if merged.exit:
            raise Stop(1, f"git merge-tree failed (exit {merged.exit}): {merged.err.strip()[:200]}")
        tree = merged.out.split()[0]
        q = self.git("commit-tree", tree, "-p", parent, "-m", f"queue {n}: {head[:12]}")
        ref = f"{PREFIX}{n}-{head[:12]}"
        self.git("update-ref", ref, q)
        return Made(q=q, tree=tree, ref=ref)

    def drop(self, ref: str) -> None:
        self.git("update-ref", "-d", ref)
