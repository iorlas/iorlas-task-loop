"""The factory's commit of what a stage's agent listed, outside the sandbox, and the clean-tree check at its result.

Git and the slot file port only: no factory.db (the verifier stores what this module finds). The only factory module
that calls `stage` or `record`. The slot pointer is checked before any Git call on the slot and again right before each
of the two Git writes; the agent's own commit cannot happen under the sandbox, so a moved HEAD is adopted only when it is
this attempt's own trailer commit from a crash before its recording. `GitUnavailable` and `Unreadable` propagate.
"""

from dataclasses import dataclass
from pathlib import Path

from git_porcelain import NothingToRecord, Recorded, Repo

from taskloop.plan_types import TRAILER, Admission, AnswerState, Checkouts, Rejected, SlotFiles, StageRules, Unsettled
from taskloop.plan_verify import SlotState, listing, observe_slot, pointer


class NotSettled(Exception):
    """Unknown, nothing staged or stored (`repo`, `not_listed`, `git:HookRejected`): `reason` is fixed words."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Committed:
    """X, the commit the stage ends at: the factory's new commit, an adopted crash leftover, or B for `unchanged`."""

    sha: str


type Settled = Committed | Unsettled | Rejected


def attributes(rules: StageRules) -> tuple[str, ...]:
    """Where an ignored file would change how the listed paths are staged, though status never shows it."""
    return (".gitattributes", "docs/.gitattributes", "docs/design/.gitattributes", rules.root)


def _observed(checkouts: Checkouts, files: SlotFiles, admission: Admission) -> SlotState | Unsettled:
    state = observe_slot(checkouts, files, admission.cwd, admission.repo_id)
    if state == "redirected":
        return Unsettled("redirected")
    if isinstance(state, str):
        raise NotSettled(state)
    return state


def _redirected(files: SlotFiles, admission: Admission, root: Path) -> bool:
    found = pointer(files, Path(admission.cwd))
    return found is None or found.root != root


def trailer(admission: Admission) -> str:
    return f"{TRAILER}: {admission.key.attempt_id}"


def settle(checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str, answer: AnswerState) -> Settled:
    """Steps 2 to 5 of the stage commit for a valid `planned` or `unchanged` answer with no stored `plan_commit`."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    head = state.head
    if head is None or state.branch is not None:
        return Unsettled("unborn" if head is None else "branch")
    if answer.disposition == "unchanged":  # X is B: an `unchanged` stage never adopts a commit
        return Committed(base) if head == base else Unsettled("head_moved")
    if head != base:
        return Committed(head) if _ours(checkouts(state.root), head, base, admission) else Unsettled("head_moved")
    return _commit(checkouts, files, admission, state.root, base, answer)


def _commit(checkouts: Checkouts, files: SlotFiles, admission: Admission, root: Path, base: str, answer: AnswerState) -> Settled:
    """Step 4 (the listed paths, Git's own files near them, ignored files), then step 5: stage exactly the listed paths
    and commit them with the agent's message and this attempt's trailer, the pointer checked before each Git write."""
    unsafe = unsafe_path(files, Path(admission.cwd), admission.rules, answer.paths)
    slot = checkouts(root).worktree(Path(admission.cwd))
    dirt = slot.dirty(base, ignored_under=attributes(admission.rules)) if unsafe is None else None
    unsafe = unsafe or (None if dirt is None else git_file(dirt.tracked + dirt.untracked, admission.rules, answer.paths))
    if unsafe is not None:
        return Unsettled("unsafe", (unsafe,))
    if dirt is not None and dirt.ignored:
        return Unsettled("ignored")
    if _redirected(files, admission, root):
        return Unsettled("redirected")
    slot.stage(answer.paths, literal=True)
    if _redirected(files, admission, root):
        return Unsettled("redirected")
    made = slot.record(f"{answer.message}\n\n{trailer(admission)}", paths="staged", hooks=False)
    if isinstance(made, Recorded):
        return Committed(made.sha)
    if isinstance(made, NothingToRecord):
        return _unwritten(checkouts, files, admission, base)
    raise NotSettled("git:HookRejected")  # cannot happen with hooks off: unknown, never a verdict


def _unwritten(checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str) -> Settled:
    """Nothing to commit is `nothing_written` only while HEAD is still B: a verifier racing this one may have committed
    the same index first, so a moved HEAD goes back to the adopt rule (its trailer commit) or `head_moved`."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    head = state.head
    if head is None or state.branch is not None:
        return Unsettled("unborn" if head is None else "branch")
    if head == base:
        return Rejected("nothing_written")
    return Committed(head) if _ours(checkouts(state.root), head, base, admission) else Unsettled("head_moved")


def git_file(dirty: tuple[str, ...], rules: StageRules, paths: tuple[str, ...]) -> str | None:
    """The first changed path with a component that starts with `.git` (any case: `.gitattributes`, `.gitignore`,
    `.gitmodules`, ...) sitting in a folder on the way to a listed path or under the stage root: it would change how Git
    stages the listed paths, and status shows it but the agent may not commit it."""
    chain = {"/".join(path.split("/")[:depth]) for path in paths for depth in range(path.count("/") + 1)}
    for found in dirty:
        parts = found.split("/")
        for depth, part in enumerate(parts):
            folder = "/".join(parts[:depth])
            if part.casefold().startswith(".git") and (folder in chain or (folder + "/").startswith(rules.root)):
                return found
    return None


def _ours(repo: Repo, head: str, base: str, admission: Admission) -> bool:
    """H is exactly one commit beyond B whose message carries this attempt's trailer line: the factory's own commit."""
    found = repo.history([head], not_on=[base])
    return len(found) == 1 and found[0].sha == head and trailer(admission) in found[0].body.splitlines()


def unsafe_path(files: SlotFiles, slot: Path, rules: StageRules, paths: tuple[str, ...]) -> str | None:
    """The first listed path that is not a plain regular file reached through plain directories: no component a symlink
    (`lstat` per component), no execute bit, at most `file_cap` bytes; None when every one is safe."""
    for path in paths:
        parts = path.split("/")
        folders = (files.lstat(slot.joinpath(*parts[:depth])) for depth in range(1, len(parts)))
        entry = files.lstat(slot.joinpath(*parts))
        if not all(folder is not None and folder.kind == "dir" for folder in folders):
            return path
        if entry is None or entry.kind != "file" or entry.executable or entry.size > rules.file_cap:
            return path
    return None


def clean_at(checkouts: Checkouts, files: SlotFiles, admission: Admission, commit: str) -> Path | Unsettled:
    """Step 6: the slot is detached at X with nothing tracked or untracked left over (ignored files are not counted),
    returning the root its pointer names; leftovers are `uncommitted` with their listing, read fresh and never stored."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    problem = state.problem(commit)
    if problem is None:
        return state.root
    if problem != "dirty":
        return Unsettled(problem)
    return Unsettled("uncommitted", listing(checkouts(state.root), Path(admission.cwd)))


def leftovers(
    checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str, answer: AnswerState, plan_commit: str | None
) -> Unsettled | None:
    """Read-only, for a person (`tl plan show`): what a verify would report as a stage to repeat, read now. Before the
    factory's commit only the listed paths are checked (`unsafe`); after it, or for `unchanged`, the clean-tree check."""
    if answer.disposition == "planned" and plan_commit is None:
        state = _observed(checkouts, files, admission)
        if isinstance(state, Unsettled) or state.head != base:
            return None
        unsafe = unsafe_path(files, Path(admission.cwd), admission.rules, answer.paths)
        return None if unsafe is None else Unsettled("unsafe", (unsafe,))
    found = clean_at(checkouts, files, admission, plan_commit or base)
    return found if isinstance(found, Unsettled) else None
