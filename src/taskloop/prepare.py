"""Read-only branch admission and selection of a retained source under slot custody.

Each detached D must belong to the selected source or origin's known main history. Existing task work is selected
local-first, otherwise remote-tracking; a new branch starts at local main. D only chooses eligibility and the release
park point. Branch ownership, foreign unpublished work and the previous published X remain fenced. A take must match
the selected source exactly, including when D belongs to main rather than the task branch.

`merge.prepare.SourcePreparation` continues clean preparation before ordinary setup/dispatch: fetch origin's main,
merge it into the retained source, reconcile pending actions and attach the accepted result. That completed HEAD is B;
repeat leftovers bypass this merge. These source-selection functions themselves never fetch. Missing revisions and
failed reads stay unavailable; a missing previous X is `branch_moved`. `detach_at` prepares checks slots at X detached.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import BranchHeld, GitUnavailable, MissingRevision, Repo

from taskloop.attempt_types import TRAILER, AttemptRecord, AttemptResult, Checkouts, SlotFiles
from taskloop.slot_state import SlotState, observe_slot, pointer, staged
from taskloop.slots import SlotView, unusable_text

type BranchRefusal = Literal["branch_name", "branch_held", "branch_diverged", "branch_unpublished", "target"]
MAIN: Final = "refs/heads/main"  # the target (O1: the person's local `main`): a new task branch starts at its tip, checks read it
ORIGIN_MAIN: Final = "refs/remotes/origin/main"
HEADS: Final = "refs/heads/task"
REMOTES: Final = "refs/remotes/origin/task"
NAME: Final = re.compile(r"[A-Za-z0-9._-]+")


def task_branch(task_id: str) -> str:
    """The glossary's derivation; never stored."""
    return f"task/{task_id}"


@dataclass(frozen=True)
class Branch:
    """The task branch as read now: the given heads (D) below its selected start or origin's known main, the task tips
    (None when absent), and `start`, the commit the slot takes: the local tip, else the remote-tracking one, else (a new
    branch) `main`'s tip."""

    passing: tuple[str, ...]
    local: str | None
    remote: str | None
    start: str


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


def _foreign_unpublished(repo: Repo, local: str, seen: Sequence[str]) -> bool:
    """A commit on the local branch that no `seen` tip (origin's, `main`'s: a merge of `main` is not new work) holds and that
    no factory attempt made (no `TRAILER` line): the person's own work, which a publish would push. The factory's own
    unpublished commits (an abandoned attempt's X) are resumed."""
    if not seen:
        return False
    return any(not any(line.startswith(f"{TRAILER}:") for line in each.body.splitlines()) for each in repo.history([local], not_on=seen))


HELD_SLOT = (
    "task/{task} is checked out in a slot ({slots}; the round log reports it `unusable`): run `git switch --detach` there "
    "(commit or stash what it holds first, nothing is deleted for you), then `tl slot adopt` if it is not adopted."
)
HELD_MAIN = "task/{task} is checked out in your main checkout ({path}): switch it off the branch yourself, then start again."
HELD_OTHER = "task/{task} is checked out in {path}, which is not a slot: switch it off the branch yourself, then start again."
def refusal_detail(found: BranchRefusal, task_id: str) -> str:
    return DETAILS.get(found, "").format(task=task_id)


def held_refusal(repo: Repo, task_id: str, free: tuple[SlotView, ...]) -> tuple[tuple[SlotView, ...], str]:
    """`branch_held`: the worktrees on the task branch, each told apart. A sibling of a free slot (same `<root>/<repo id>`
    folder) is a slot, adopted or not (after a factory.db discard `tl slot adopt` refuses it `attached`, so no slot row
    names it): an `attached` view named by its folder, which the round log reports `unusable`. The person's main checkout
    and any other worktree are named in the detail only: no slot, so `tl slot adopt` does not apply."""
    branch, roots = task_branch(task_id), {view.path.parent for view in free}
    slots: list[SlotView] = []
    other: list[str] = []
    for info in (each for each in repo.worktrees() if each.branch == branch):
        if not info.is_main and info.path.parent in roots:
            slots.append(SlotView(info.path.name, info.path, "unknown", "attached"))
        else:
            other.append((HELD_MAIN if info.is_main else HELD_OTHER).format(task=task_id, path=info.path))
    named = [HELD_SLOT.format(task=task_id, slots=unusable_text(tuple(slots)))] if slots else []
    return tuple(slots), " ".join([*named, *other])


def branch_refusal(repo: Repo, task_id: str, heads: Sequence[str]) -> BranchRefusal | Branch:
    """Name, ref collisions, checked-out ownership, then ancestry and unpublished-work protection. D may be below the
    selected source or known origin main. Ordinary forks merge during execution; unrelated histories refuse. Missing
    main knowledge is `target` when the selected source cannot establish eligibility. A stale non-selected task ref
    does not constrain D. Main's known commits and factory-owned work are not foreign unpublished task commits."""
    if not named(task_id):
        return "branch_name"
    found = {entry.name: entry.sha for entry in repo.refs([HEADS, REMOTES, MAIN, ORIGIN_MAIN])}
    if _clash(tuple(found), task_id):
        return "branch_name"
    if any(info.branch == task_branch(task_id) for info in repo.worktrees()):
        return "branch_held"
    local, remote = found.get(f"{HEADS}/{task_id}"), found.get(f"{REMOTES}/{task_id}")
    target = found.get(MAIN)
    tips = tuple(tip for tip in (local, remote) if tip is not None) or ((target,) if target is not None else ())
    if not tips:
        return "target"
    start = tips[0]
    origin = found.get(ORIGIN_MAIN)
    passing = tuple(head for head in heads if repo.is_ancestor(head, start) or (origin is not None and repo.is_ancestor(head, origin)))
    if (heads and not passing) or not _related(repo, start, origin):
        return "target" if origin is None else "branch_diverged"
    unpublished = local is not None and _foreign_unpublished(repo, local, [tip for tip in (remote, target, origin) if tip is not None])
    return "branch_unpublished" if unpublished else Branch(passing, local, remote, start)


def _related(repo: Repo, start: str, origin: str | None) -> bool:
    if origin is None:
        return True
    repo.is_ancestor(start, start)  # missing required revisions remain unavailable, not unrelated history
    repo.is_ancestor(origin, origin)
    return repo.merge_base(start, origin) is not None


DIVERGED: Final = (
    "The selected task/{task} history is unrelated to origin's known main, or no free slot's commit belongs to either history. "
    "The task's work is retained; preparation is refused until a slot with a valid base is available. "
    "A new task starts at your local main. Main advancing beyond an existing task branch does not require a restart."
)


UNPUBLISHED: Final = (
    "The local task/{task} has commits that are not on origin (`git log --oneline main..task/{task}` or `git log "
    "--oneline origin/task/{task}..task/{task}` lists them) and a publish would push them: rename the branch (`git branch -m "
    "task/{task} old/task/{task}`), or push it by hand, then start again."
)


DETAILS: Final = {
    "branch_diverged": DIVERGED,
    "branch_unpublished": UNPUBLISHED,
    "target": f"The checkout lacks a required target: `{MAIN}` for a new task, or `{ORIGIN_MAIN}` to validate a slot base."}


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
    exists, else at `main`'s tip. D may belong only to origin main. None once the slot is on its branch."""
    admission, head = record.admission, state.head or ""
    task_id = admission.task.task_id
    repo = checkouts(state.root)
    found = branch_refusal(repo, task_id, (head,))
    if isinstance(found, str):
        return _refused(found)
    after = admission.after_commit
    if after is not None and (lacks(repo, after, found.start) or (admission.source_checks_id is not None and found.start != after)):
        return _refused("branch_moved")
    named = pointer(files, Path(admission.slot_path))
    if named is None or named.root != state.root or named.gitdir != state.gitdir:
        return _refused("slot_redirected")
    slot = Path(admission.slot_path)
    worktree = checkouts(slot, git_dir=state.gitdir).worktree(slot)
    taken = worktree.take_branch(task_branch(task_id), found.start, mode="resume")
    if isinstance(taken, BranchHeld):
        return _refused("branch_held")
    changed = taken.head != found.start
    diverged = changed and repo.merge_base(found.start, taken.head) is None
    moved = (changed and not diverged) or (after is not None and (lacks(repo, after, taken.head)
                                         or (admission.source_checks_id is not None and taken.head != after)))
    if not diverged and not moved:
        return None
    # A source substituted between the rule and take never dispatches, even when D is safely on main.
    worktree.park(head)
    return _refused("branch_moved" if moved else "branch_diverged")


def lacks(repo: Repo, after: str, tip: str) -> bool:
    """The tip the slot would take (the local branch, else the remote-tracking one, else `main`'s) does not contain the previous
    step's published X, or X is gone from the repository: someone reset or deleted the branch after that step."""
    try:
        return not repo.is_ancestor(after, tip)
    except MissingRevision:
        return True


def _prepared(checkouts: Checkouts, files: SlotFiles, record: AttemptRecord) -> SlotState | AttemptResult:
    """The slot after preparation: already on a branch, or a repeat's slot, is read as it is (no Git write); a detached
    slot of attempt 1 must be clean, then takes its branch and is read again."""
    state = _observed(checkouts, files, record)
    inherited = record.start is not None and record.admission.source_checks_id is None
    if isinstance(state, AttemptResult) or state.branch is not None or inherited:
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
    if record.admission.source_checks_id is not None and record.base_commit is None:
        if state.head != record.admission.after_commit:
            return _refused("branch_moved")
        if state.dirty:
            return _refused("slot_dirty")
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
    # a Git read is bounded (`git_read_seconds`), not by the attempt deadline: that is checked again right before the dispatch write
    return _refused("expired") if clock() >= deadline else Prepared(state.head, state.gitdir, state.root)
