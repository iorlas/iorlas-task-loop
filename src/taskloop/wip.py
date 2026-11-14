"""Saved work: the commit a hold makes of a slot's uncommitted changes on the task branch, and what marks it.

A hold saves, never resets: the slot's final working state (`capture`: staged and unstaged edits, deletions, renames,
untracked files that no ignore rule hides) becomes one commit on `task/<id>`, parented on the branch's tip (D when the
branch does not exist yet), made in Git objects only and moved onto the ref by compare and swap. The checkout's index
then follows the saved commit (a mixed reset: no working byte changes), and the slot is parked at D with its ignored
files kept (`park(keep_ignored=True)`). A saved commit is preservation, never an implementation result: it carries the
attempt's own trailer (the branch stays resumable) and the typed `Task-Loop-Wip` trailer, and checks admission, publication
and land refuse a commit that has it (`is_saved`). Reconciliation asks Git: a branch tip that is this attempt's saved
commit of the captured tree is adopted, never duplicated.

With explicitly recorded merge inputs, the preservation commit also retains those commits and the detached HEAD as
parents. Unresolved files are staged for capture; the merge and working files stay in place until the owning release
reconciles the durable save and aborts the merge. An unaccounted merge refuses preservation and parking.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
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
    """Where a save comes from: the task, attempt, slot, admission base D and optional immutable merge inputs."""

    task_id: str
    attempt_id: str
    slot: str
    base: str
    merge: tuple[str, str] | None = None  # the recorded starting commit and target, retained even after finish_merge


class SaveReason(StrEnum):
    REF_MOVED = "ref_moved"
    MERGE_INPUTS = "merge_inputs"
    MERGE_CHANGED = "merge_changed"
    MERGE_PENDING = "merge_pending"


@dataclass(frozen=True)
class Refused:
    """Preservation or parking stopped; the working files remain in the reserved slot."""

    reason: SaveReason
    detail: str


def message(source: Source) -> str:
    text = f"Save unfinished work of {source.task_id}\n\n{TRAILER}: {source.attempt_id}\n{WIP}: {source.attempt_id}"
    if source.merge is not None:
        text += f"\nTask-Loop-Merge-Start: {source.merge[0]}\nTask-Loop-Merge-Target: {source.merge[1]}"
    return text


def is_saved(repo: Repo, sha: str) -> bool:
    """Whether `sha` is a saved commit (its typed trailer), never a guess from its subject."""
    found = repo.history([sha], limit=1)
    return bool(found) and found[0].sha == sha and any(line.startswith(f"{WIP}: ") for line in found[0].body.splitlines())


def needs_review(repo: Repo, sha: str) -> bool:
    """A factory merge above saved work retains its review requirement until an ordinary step records its result."""
    seen: set[str] = set()
    while sha not in seen:
        if is_saved(repo, sha):
            return True
        seen.add(sha)
        found = repo.history([sha], limit=1)
        if not found:
            return False
        lines = found[0].body.splitlines()
        source = next((line.removeprefix("Task-Loop-Merge-Start: ") for line in lines
                       if line.startswith("Task-Loop-Merge-Start: ")), None)
        first, second = repo.tree(f"{sha}^1"), repo.tree(f"{sha}^2")
        if (source is None or first is None or first.sha != source or second is None
                or f"Task-Loop-Merge-Target: {second.sha}" not in lines
                or not any(line.startswith(f"{TRAILER}: ") for line in lines)):
            return False
        sha = source
    return False


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
    slot's lock, after the stop proof. With recorded merge inputs, preserve both sides and the detached HEAD in the
    saved commit's ancestry. Stage unresolved entries only for capture, preserving their working bytes (including
    markers). Leave the merge and checkout in place: its owning release must observe the durable save before aborting.
    Ordinary saves retain their existing mixed reset. None means saved (or nothing to save) and recorded."""
    merging = slot.merging()
    if merging and source.merge is None:
        return Refused(SaveReason.MERGE_INPUTS, "The slot has a merge in progress without recorded inputs. Its work remains reserved.")
    if merging and source.merge is not None and head != source.merge[0]:
        return Refused(SaveReason.MERGE_CHANGED, "The slot's merge no longer starts at the recorded commit. Its work remains reserved.")
    if not merging and source.merge is not None:
        ancestors = {str(each.sha) for each in repo.history([head])}
        if head not in source.merge and not set(source.merge) <= ancestors:
            return Refused(SaveReason.MERGE_CHANGED,
                           "The slot's HEAD does not retain both recorded merge inputs. Its work remains reserved.")
    tip = _tip(repo, source.task_id)
    parent = tip or source.base
    if source.merge is not None:
        # capture refuses an unmerged index. Staging here preserves the working files and both committed sides;
        # this is preservation after a stop proof, never acceptance of a resolution or a land candidate.
        paths = slot.unmerged()
        if paths:
            slot.stage(paths)
    tree = slot.capture()
    ref = f"refs/heads/{task_branch(source.task_id)}"
    made = tip if tip is not None and _saved_tree(repo, tip, source, head, str(tree)) else None
    if made is None and (source.merge is not None or not _same(repo, str(tree), parent)):
        parents = (parent,) if source.merge is None else tuple(dict.fromkeys((parent, head, *source.merge)))
        wip = repo.commit_tree(str(tree), parents, message(source), when=when)
        moved = repo.update_ref(ref, str(wip), expected=tip)
        if isinstance(moved, RefMoved):
            return Refused(SaveReason.REF_MOVED, f"{task_branch(source.task_id)} moved while the slot's work was being saved. "
                           "The working files remain in the slot.")
        made = str(wip)
    if made is not None:
        if made not in {each.sha for each in log.saved(source.attempt_id)}:
            log.add(source.attempt_id, SavedCommit(sha=made, attempt_id=source.attempt_id, slot=source.slot, source_head=head))
        if source.merge is None:
            slot.reset(made, mode="mixed")
    return None


def _saved_tree(repo: Repo, tip: str, source: Source, head: str, tree: str) -> bool:
    """Adopt the same save after a crash only when its recorded inputs and working tree agree."""
    if not _ours(repo, tip, source) or not _same(repo, tip, tree):
        return False
    if source.merge is None:
        return True
    found = repo.history([tip], limit=1)
    return (bool(found) and found[0].body.strip() == message(source).partition("\n\n")[2]
            and head in {str(each.sha) for each in repo.history([tip])})


def park(slot: Worktree, base: str) -> str | Refused:
    """After a save: detach at D, the ignored files kept. A merge's owner must reconcile and abort it first."""
    if slot.merging():
        return Refused(SaveReason.MERGE_PENDING,
                       "The slot still has a merge in progress. Its owning release must preserve it and abort it before parking.")
    return str(slot.park(base, keep_ignored=True))

