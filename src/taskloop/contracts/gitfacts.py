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
class GitOutcome(Rec):
    """How a git command that may fail for a reason the caller reads ended: `ok`, and git's words (stdout and stderr). A rebase that
    failed is left in progress (rebase_abort undoes it)."""

    ok: bool
    output: str = ""


@final
class GrepHit(Rec):
    """One matching line of `git grep -n`: the tracked file, its 1-based line number and the line."""

    path: str
    line: int
    text: str


@final
class ConfigEntry(Rec):
    """One setting of `git config --show-origin`: where it was set (file:<path>, ...), its key and its value."""

    where: str
    key: str
    value: str


@final
class DiffEntry(Rec):
    """One path of a tree-to-tree diff with exact renames found (`-M100%`): status A, D, M, T or R; `old` is the source of a rename."""

    status: str
    path: str
    old: str = ""
