"""Slot preparation: the task branch rule and the one writer that puts a slot on its task branch.

`branch_refusal` is the one branch rule (a pure name check, then read-only Git: local refs, the worktree listing and
ancestry), used by admission before anything is held and again by the entry right before it creates the branch.
`base` is the entry's preparation and base read for an `admitted` attempt, under the slot's custody lock: attempt 1 on a
clean detached slot takes `task/<task-id>` (`take_branch(mode="resume")`, the only factory call of it, and `park` back
to D when a branch made after the rule turns out not to contain D); attempt 1 of a later step first requires that
branch to contain the previous step's published X (`after_commit`, else `branch_moved`); B is then the
HEAD on that branch. No fetch: only local refs, including the local remote-tracking ones, are read. Every refusal is one
fixed word and leaves the attempt `admitted`; `GitUnavailable` (a missing revision or a failed read included) is
`unavailable:git`, never "absent", except that a missing `after_commit` is `branch_moved` (the branch lost it).
`detach_at` is a checks slot's preparation: X taken detached (`park`), never a branch.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import BranchHeld, GitUnavailable, MissingRevision, Repo

from taskloop.attempt_types import AttemptRecord, AttemptResult, Checkouts, SlotFiles
from taskloop.slot_state import SlotState, observe_slot, pointer, staged

type BranchRefusal = Literal["branch_name", "branch_held", "branch_diverged"]
HEADS: Final = "refs/heads/task"
REMOTES: Final = "refs/remotes/origin/task"
NAME: Final = re.compile(r"[A-Za-z0-9._-]+")


def task_branch(task_id: str) -> str:
    """The glossary's derivation; never stored."""
    return f"task/{task_id}"


@dataclass(frozen=True)
class Branch:
    """The task branch as read now: the given heads (D) that every existing tip contains, and the local and local
    remote-tracking tips (None when absent)."""

    passing: tuple[str, ...]
    local: str | None
    remote: str | None


def named(task_id: str) -> bool:
    """A task id that is one safe ref component: `[A-Za-z0-9._-]+`, no leading `.` or `-`, no `..`, no trailing `.`,
    no `.lock` suffix."""
    return (
        NAME.fullmatch(task_id) is not None
        and not task_id.startswith((".", "-"))
        and ".." not in task_id
        and not task_id.endswith((".", ".lock"))
    )


def _clash(names: Sequence[str], task_id: str) -> bool:
    """`refs/heads/task` itself, a ref under `task/<id>/` (a directory/file conflict), or another local `task/*` whose
    name casefolds equal to ours (it collides on a case-insensitive file system)."""
    ours = f"{HEADS}/{task_id}"
    twin = {name for name in names if name.startswith(HEADS + "/") and name != ours and name.casefold() == ours.casefold()}
    return bool(twin) or any(name == HEADS or name.startswith(ours + "/") for name in names)


def branch_refusal(repo: Repo, task_id: str, heads: Sequence[str]) -> BranchRefusal | Branch:
    """The one branch rule, in order: the name (no Git), one refs read (`branch_name` on a conflict), the worktree
    listing (`branch_held` when any worktree is on the branch), then history: each given head D passes when the local
    tip and the local remote-tracking tip, where present, both contain it (`branch_diverged` when none does)."""
    if not named(task_id):
        return "branch_name"
    found = {entry.name: entry.sha for entry in repo.refs([HEADS, REMOTES])}
    if _clash(tuple(found), task_id):
        return "branch_name"
    if any(info.branch == task_branch(task_id) for info in repo.worktrees()):
        return "branch_held"
    local, remote = found.get(f"{HEADS}/{task_id}"), found.get(f"{REMOTES}/{task_id}")
    tips = [tip for tip in (local, remote) if tip is not None]
    passing = tuple(head for head in heads if all(repo.is_ancestor(head, tip) for tip in tips))
    return "branch_diverged" if heads and not passing else Branch(passing, local, remote)


DIVERGED: Final = (
    "An existing task/{task} does not contain the slot's commit. A local branch: rename it (`git branch -m task/{task} "
    "old/task/{task}`) or delete it. Only origin's remote-tracking ref: delete the branch on origin (`git push origin "
    "--delete task/{task}`), or drop the local ref (`git update-ref -d refs/remotes/origin/task/{task}`) and do not fetch "
    "it again."
)


def _refused(reason: str) -> AttemptResult:
    return AttemptResult("refused", reason)


def _observed(checkouts: Checkouts, files: SlotFiles, record: AttemptRecord) -> SlotState | AttemptResult:
    """The slot as Git lists it, the pointer checked first (no Git call on `redirected`); born."""
    admission = record.admission
    state = observe_slot(checkouts, files, admission.slot_path, admission.repo_id)
    if state == "redirected":
        return _refused("slot_redirected")
    if isinstance(state, str):
        return AttemptResult("unavailable", state)
    return _refused("slot_unborn") if state.head is None else state


def _take(checkouts: Checkouts, files: SlotFiles, record: AttemptRecord, state: SlotState) -> AttemptResult | None:
    """Attempt 1 on a clean detached slot at D: the branch rule again, the pointer again, then `take_branch` on the slot's
    own view. An existing local branch is checked out as it is; a new one starts at the remote-tracking tip when that
    exists (it contains D), else at D. None once the slot is on its branch."""
    admission, head = record.admission, state.head or ""
    task_id = admission.task.task_id
    repo = checkouts(state.root)
    found = branch_refusal(repo, task_id, (head,))
    if isinstance(found, str):
        return _refused(found)
    after = admission.after_commit
    if after is not None and lacks(repo, after, found.local or found.remote or head):
        return _refused("branch_moved")
    named = pointer(files, Path(admission.slot_path))
    if named is None or named.root != state.root or named.gitdir != state.gitdir:
        return _refused("slot_redirected")
    start = found.remote if found.local is None and found.remote is not None else head
    slot = Path(admission.slot_path)
    worktree = checkouts(slot, git_dir=state.gitdir).worktree(slot)
    taken = worktree.take_branch(task_branch(task_id), start, mode="resume")
    if isinstance(taken, BranchHeld):
        return _refused("branch_held")
    diverged = not repo.is_ancestor(head, taken.head)
    moved = after is not None and lacks(repo, after, taken.head)
    if not diverged and not moved:
        return None
    # a branch made or moved between the rule and the take was checked out as it is, without D or without the previous
    # step's X: back to D, detached, so the next entry refuses it again instead of starting from that tip
    worktree.park(head)
    return _refused("branch_diverged" if diverged else "branch_moved")


def lacks(repo: Repo, after: str, tip: str) -> bool:
    """The tip the slot would take (the local branch, else the remote-tracking one, else D) does not contain the previous
    step's published X, or X is gone from the repository: someone reset or deleted the branch after that step."""
    try:
        return not repo.is_ancestor(after, tip)
    except MissingRevision:
        return True


def _prepared(checkouts: Checkouts, files: SlotFiles, record: AttemptRecord) -> SlotState | AttemptResult:
    """The slot after preparation: already on a branch, or a repeat's slot, is read as it is (no Git write); a detached
    slot of attempt 1 must be clean, then takes its branch and is read again."""
    state = _observed(checkouts, files, record)
    if isinstance(state, AttemptResult) or state.branch is not None or record.start is not None:
        return state
    if state.dirty:
        return _refused("slot_dirty")
    taken = _take(checkouts, files, record, state)
    return _observed(checkouts, files, record) if taken is None else taken


def _state_refusal(checkouts: Checkouts, record: AttemptRecord, state: SlotState) -> AttemptResult | None:
    """The base check: on exactly `task/<task-id>`; clean for attempt 1 and, for attempt 1 of a later step, containing
    the previous step's X (a relaunch finds the slot on its branch already), or at E with nothing staged for a repeat
    (its leftovers are its feedback, but the factory's commit records the whole index)."""
    if state.branch is None:
        return _refused("slot_detached")
    problem = state.problem(task_branch(record.admission.task.task_id), record.start)
    after = record.admission.after_commit
    if record.start is None and problem is None and after is not None and lacks(checkouts(state.root), after, state.head or ""):
        return _refused("branch_moved")
    if record.start is None or problem != "dirty":
        return None if problem is None else _refused(f"slot_{problem}")
    path = Path(record.admission.slot_path)
    return _refused("slot_staged") if staged(checkouts(path, git_dir=state.gitdir), path) else None


@dataclass(frozen=True)
class Prepared:
    """The slot on its task branch: `head` is B; `gitdir` the Git directory its verified pointer names (every later Git
    view of the slot is pinned to it); `root` the person's checkout that pointer names."""

    head: str
    gitdir: Path
    root: Path


def detach_at(checkouts: Checkouts, files: SlotFiles, slot_path: str, repo_id: str, commit: str) -> Prepared | AttemptResult:
    """A checks slot takes X detached (the checks entry, under the slot's custody lock; never `task/<id>`). In order: a
    redirected pointer `slot:redirected`, an unborn slot `slot_unborn`, a slot on a branch `slot:branch`, X gone from the
    repository `commit_missing`; a slot already detached at X passes in any state (the environment's reset makes it
    exactly X); a detached slot elsewhere with changes is `slot_dirty` (a free slot is clean at admission); a clean one is
    parked at X through its pinned view and read again, which must give `(X, detached)` (else `slot:moved`). `prepare`'s
    other words (`unavailable` `repo`, `not_listed`, `git`) as for an agent slot."""
    try:
        state = slot_listed(checkouts, files, slot_path, repo_id)
        if isinstance(state, AttemptResult):
            return state
        problem = _detached_problem(checkouts, state, commit)
        if problem is not None or state.head == commit:
            return problem or Prepared(commit, state.gitdir, state.root)
        path = Path(slot_path)
        checkouts(path, git_dir=state.gitdir).worktree(path).park(commit)
        again = slot_listed(checkouts, files, slot_path, repo_id)
    except GitUnavailable:
        return AttemptResult("unavailable", "git")
    if isinstance(again, AttemptResult) or (again.head, again.branch) == (commit, None):
        return again if isinstance(again, AttemptResult) else Prepared(commit, again.gitdir, again.root)
    return _refused("slot:moved")


def slot_listed(checkouts: Checkouts, files: SlotFiles, slot_path: str, repo_id: str) -> SlotState | AttemptResult:
    """`observe_slot` in `detach_at`'s words (also the checks entry's read of the slot's pinned Git directory before X is taken)."""
    state = observe_slot(checkouts, files, slot_path, repo_id)
    if state == "redirected":
        return _refused("slot:redirected")
    return AttemptResult("unavailable", state) if isinstance(state, str) else state


def _detached_problem(checkouts: Checkouts, state: SlotState, commit: str) -> AttemptResult | None:
    """`detach_at`'s refusals of a listed slot before any write."""
    if state.head is None:
        return _refused("slot_unborn")
    if state.branch is not None:
        return _refused("slot:branch")
    if lacks(checkouts(state.root), commit, commit):
        return _refused("commit_missing")
    return _refused("slot_dirty") if state.dirty and state.head != commit else None


def base(checkouts: Checkouts, files: SlotFiles, record: AttemptRecord, clock: Callable[[], float]) -> Prepared | AttemptResult:
    """B and the slot's verified Git directory: the slot's HEAD on its task branch, prepared and read just before
    dispatch while the deadline is ahead."""
    deadline = record.admission.deadline
    if clock() >= deadline:  # crossed while resolving the launch: stays admitted
        return _refused("expired")
    try:
        state = _prepared(checkouts, files, record)
        if isinstance(state, SlotState):
            state = _state_refusal(checkouts, record, state) or state
    except GitUnavailable:
        return AttemptResult("unavailable", "git")
    if isinstance(state, AttemptResult) or state.head is None:
        return state if isinstance(state, AttemptResult) else _refused("slot_unborn")
    # the Git reads have no timeout: the deadline is checked again right before the dispatch write
    return _refused("expired") if clock() >= deadline else Prepared(state.head, state.gitdir, state.root)
