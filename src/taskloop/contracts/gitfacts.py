"""What the Git port answers with: git's rows as typed records, so no caller re-parses git's text."""
from typing import Final, final

from taskloop.contracts.wire import Rec

DETACHED: Final = ""


@final
class Ref(Rec):
    """A ref and the oid it is at. `name` is what the question asked for: the full refname (for-each-ref, ls-remote) or the short
    branch name (merged)."""

    name: str
    oid: str


@final
class Pick(Rec):
    """One commit of `git cherry`: `upstream` when a commit with the same patch is already on the upstream side."""

    oid: str
    upstream: bool


@final
class LogRow(Rec):
    """One commit of a log: oid, committer time (epoch seconds) and subject."""

    oid: str
    time: int
    subject: str


@final
class TreeEntry(Rec):
    """One row of ls-tree: mode, kind (blob, tree, commit), object id and the path."""

    mode: str
    kind: str
    oid: str
    path: str


@final
class StatusRow(Rec):
    """One path of `git status`: the index letter and the work-tree letter (' ' for none); untracked is '?' and '?'."""

    path: str
    index: str
    work: str

    @property
    def untracked(self) -> bool:
        return self.index == "?"


@final
class RebaseOutcome(Rec):
    """How a rebase ended: `ok`, else git's words. A failed rebase is left in progress (rebase_abort undoes it)."""

    ok: bool
    output: str = ""
