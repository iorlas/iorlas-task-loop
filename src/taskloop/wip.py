"""Saved work: the commit a hold makes of a slot's uncommitted changes on the task branch, and what marks it.

A hold saves, never resets: the slot's final working state (`capture`: staged and unstaged edits, deletions, renames,
untracked files that no ignore rule hides) becomes one commit on `task/<id>`, parented on the branch's tip (D when the
branch does not exist yet), made in Git objects only and moved onto the ref by compare and swap. The checkout's index
then follows the saved commit (a mixed reset: no working byte changes), and the slot is parked at D with its ignored
files kept (`park(keep_ignored=True)`). A saved commit is preservation, never an implementation result: it carries the
attempt's own trailer (the branch stays resumable) and the typed `Task-Loop-Wip` trailer, and checks admission, publication
and land refuse a commit that has it (`is_saved`). Reconciliation asks Git: a branch tip that is this attempt's saved
commit of the captured tree is adopted, never duplicated.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from git_porcelain import RefMoved, Repo, Worktree
from pydantic import BaseModel, ConfigDict, TypeAdapter

from taskloop.attempt_types import TRAILER
from taskloop.prepare import task_branch

WIP: Final = "Task-Loop-Wip"  # the trailer that marks a saved commit; the attempt's own trailer is `attempt_types.TRAILER`


class SavedCommit(BaseModel):
    """One saved commit: its full id, the attempt and slot it was taken from, and the slot's HEAD then."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: str
    attempt_id: str
    slot: str
    source_head: str


_CODEC: Final = TypeAdapter(tuple[SavedCommit, ...])


def encode(saved: Sequence[SavedCommit]) -> str:
    """The one JSON boundary of a hold's saved commits (`hold_store`'s column)."""
    return _CODEC.dump_json(tuple(saved)).decode()


def decode(text: str) -> tuple[SavedCommit, ...]:
    return _CODEC.validate_json(text)


class SavedLog(Protocol):
    """A hold's record of what it saved: `held` is whether the attempt has a hold at all (only a hold saves)."""

    def held(self, attempt_id: str) -> bool: ...
    def saved(self, attempt_id: str) -> tuple[SavedCommit, ...]: ...
    def add(self, attempt_id: str, commit: SavedCommit) -> None: ...


@dataclass(frozen=True)
class Source:
    """Where a save comes from: the task, the attempt and its slot, and the slot's admission base D."""

    task_id: str
    attempt_id: str
    slot: str
    base: str


@dataclass(frozen=True)
class Refused:
    """The save did not happen and nothing changed; `reason` is a fixed word."""

    reason: str
    detail: str


def message(source: Source) -> str:
    return f"Save unfinished work of {source.task_id}\n\n{TRAILER}: {source.attempt_id}\n{WIP}: {source.attempt_id}"


def is_saved(repo: Repo, sha: str) -> bool:
    """Whether `sha` is a saved commit (its typed trailer), never a guess from its subject."""
    found = repo.history([sha], limit=1)
    return bool(found) and found[0].sha == sha and any(line.startswith(f"{WIP}: ") for line in found[0].body.splitlines())


def _tip(repo: Repo, task_id: str) -> str | None:
    name = task_branch(task_id)
    return next((str(sha) for found, sha in repo.branches(name) if found == name), None)


def _same(repo: Repo, a: str, b: str) -> bool:
    """Whether two commit-ishes or tree ids name the same files."""
    left, right = repo.tree(a), repo.tree(b)
    return left is not None and right is not None and dict(left.files) == dict(right.files)


def _ours(repo: Repo, sha: str, source: Source) -> bool:
    found = repo.history([sha], limit=1)
    return bool(found) and f"{WIP}: {source.attempt_id}" in found[0].body.splitlines()


def adopt(repo: Repo, head: str, source: Source, log: SavedLog) -> None:
    """A slot already at this attempt's saved commit (a crash after the save, before its record) records it now."""
    if _ours(repo, head, source) and head not in {each.sha for each in log.saved(source.attempt_id)}:
        log.add(source.attempt_id, SavedCommit(sha=head, attempt_id=source.attempt_id, slot=source.slot, source_head=head))


def save(repo: Repo, slot: Worktree, source: Source, head: str, when: int, log: SavedLog) -> Refused | None:
    """Save the slot's working state on the task branch, record it, and bring the checkout's index to it. Under the
    slot's lock, after the stop proof. None: saved (or nothing to save) and recorded; the slot is then clean."""
    tip = _tip(repo, source.task_id)
    parent = tip or source.base
    tree = slot.capture()
    ref = f"refs/heads/{task_branch(source.task_id)}"
    made = tip if tip is not None and _ours(repo, tip, source) and _same(repo, tip, str(tree)) else None
    if made is None and not _same(repo, str(tree), parent):
        wip = repo.commit_tree(str(tree), (parent,), message(source), when=when)
        moved = repo.update_ref(ref, str(wip), expected=tip)
        if isinstance(moved, RefMoved):
            return Refused("ref_moved", f"{task_branch(source.task_id)} moved while the slot's work was being saved. Nothing changed.")
        made = str(wip)
    if made is not None:
        if made not in {each.sha for each in log.saved(source.attempt_id)}:
            log.add(source.attempt_id, SavedCommit(sha=made, attempt_id=source.attempt_id, slot=source.slot, source_head=head))
        slot.reset(made, mode="mixed")
    return None


def park(slot: Worktree, base: str) -> str:
    """After a save: detach at D, the ignored files kept ignored and on disk."""
    return str(slot.park(base, keep_ignored=True))

