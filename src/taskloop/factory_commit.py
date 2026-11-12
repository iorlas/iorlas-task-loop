"""The factory's commit of what a step's agent listed, outside the sandbox, and the clean-tree check at its result.

Git and the slot file port only: no factory.db (the verifier stores what this module finds). The only factory module
that calls `stage` or `record`. The slot pointer is checked before any Git call on the slot and again right before each
of the two Git writes, and every Git view of the slot is pinned to the Git directory that first check verified; the
agent's own commit cannot happen under the sandbox, so a moved HEAD is adopted only when it is this attempt's own trailer
commit from a crash before its recording. The caller's `quiet` is asked right before each Git write too: the worker gone
and this attempt still the reservation's holder. `GitUnavailable` and `Unreadable` propagate.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import NothingToRecord, Recorded, Repo

from taskloop.attempt_types import (
    MODE,
    TRAILER,
    Admission,
    AnswerState,
    Checkouts,
    Rejected,
    SlotFiles,
    StepRules,
    Unreadable,
    Unsettled,
    dot_git,
)
from taskloop.prepare import MAIN, task_branch
from taskloop.slot_state import SlotState, bounded, listing, observe_slot, pointer, staged
from taskloop.steps import kind


class NotSettled(Exception):
    """Unknown, nothing staged or stored (`repo`, `not_listed`, `git:HookRejected`): `reason` is fixed words."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Committed:
    """X, the commit the step ends at: the factory's new commit, an adopted crash leftover, or B for effect `keep`."""

    sha: str


type Settled = Committed | Unsettled | Rejected
type GitQuiet = Callable[[], Unsettled | None]  # None: the factory may write Git in the slot now; else why not


def attributes(rules: StepRules, paths: Sequence[str]) -> tuple[str, ...]:
    """Where an ignored file would change how the listed paths are staged, though status never shows it: the
    `.gitattributes` of every folder on the way to the step root, then the root itself (only when the root is not the
    repository, `""`); then, for each listed path, the `.gitattributes` of every folder on its way and the path itself,
    skipping what the root already covers. Each once, in that order."""
    root = rules.root
    found = [*_way(root), root] if root else []
    found += [each for path in paths for each in (*_way(path), path) if not (root and each.startswith(root))]
    return tuple(dict.fromkeys(found))


def _way(path: str) -> tuple[str, ...]:
    """The `.gitattributes` of every folder on the way to `path` (a file, or a folder ending in `/`), the top first."""
    folders = path.rstrip("/").split("/")[:-1]
    return tuple("/".join([*folders[:depth], ".gitattributes"]) for depth in range(len(folders) + 1))


def _observed(checkouts: Checkouts, files: SlotFiles, admission: Admission) -> SlotState | Unsettled:
    state = observe_slot(checkouts, files, admission.slot_path, admission.repo_id)
    if state == "redirected":
        return Unsettled("redirected")
    if isinstance(state, str):
        raise NotSettled(state)
    return state


def _redirected(files: SlotFiles, admission: Admission, state: SlotState) -> bool:
    found = pointer(files, Path(admission.slot_path))
    return found is None or found.root != state.root or found.gitdir != state.gitdir


def trailer(admission: Admission) -> str:
    return f"{TRAILER}: {admission.key.attempt_id}"


def settle(checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str, answer: AnswerState, quiet: GitQuiet) -> Settled:
    """Steps 2 to 5 of the step commit for a valid answer of effect `commit` or `keep` with no stored `end_commit`.
    `quiet` is asked right before each Git write: its answer (`worker_alive`, `superseded`) stops it, nothing written."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    head = state.head
    if head is None or state.branch != task_branch(admission.task.task_id):
        return Unsettled("unborn" if head is None else "branch")
    if answer.effect == "keep":  # X is B: a `keep` step never adopts a commit
        return Committed(base) if head == base else _moved(checkouts(state.root), head, base, admission)
    if head != base:
        view = checkouts(state.root)
        return Committed(head) if _ours(view, head, base, admission) else _moved(view, head, base, admission)
    return _commit(checkouts, files, admission, state, base, answer, quiet)


def _commit(
    checkouts: Checkouts, files: SlotFiles, admission: Admission, state: SlotState, base: str, answer: AnswerState, quiet: GitQuiet
) -> Settled:
    """Step 4 (the listed paths, Git's own files near them, ignored files), then step 5: stage exactly the listed paths
    and commit them with the agent's message and this attempt's trailer, `quiet` and the pointer checked before each Git
    write. Every slot call runs from the slot, under its ceiling, pinned to the Git directory `state` verified."""
    path = Path(admission.slot_path)
    view = checkouts(path, git_dir=state.gitdir)
    slot = view.worktree(path)
    refused = refusal(view, files, admission, base, answer)
    if refused is not None:
        return refused
    blocked = _blocked(quiet, files, admission, state)
    if blocked is not None:
        return blocked
    slot.stage(answer.paths, literal=True)
    blocked = _blocked(quiet, files, admission, state) or _foreign(checkouts, admission, answer, state.gitdir)
    if blocked is not None:
        return blocked
    made = slot.record(f"{answer.message}\n\n{trailer(admission)}", paths="staged", hooks=False)
    if isinstance(made, Recorded):
        return Committed(made.sha)
    if isinstance(made, NothingToRecord):
        return _unwritten(checkouts, files, admission, base)
    raise NotSettled("git:HookRejected")  # cannot happen with hooks off: unknown, never a verdict


def _blocked(quiet: GitQuiet, files: SlotFiles, admission: Admission, state: SlotState) -> Unsettled | None:
    """Why the next Git write may not run: the caller's `quiet` (a live worker could rewrite `.git` between the check
    and the write; another attempt took the reservation over), then the slot pointer."""
    return quiet() or (Unsettled("redirected") if _redirected(files, admission, state) else None)


def _foreign(checkouts: Checkouts, admission: Admission, answer: AnswerState, gitdir: Path) -> Unsettled | None:
    """`record` commits the whole index: any staged path the answer did not list (a person's, or an earlier attempt's
    left staged by a superseded verify) is `staged`, nothing committed."""
    path = Path(admission.slot_path)
    extra = sorted(set(staged(checkouts(path, git_dir=gitdir), path)) - set(answer.paths))
    return Unsettled("staged", bounded(extra)) if extra else None


def refusal(view: Repo, files: SlotFiles, admission: Admission, base: str, answer: AnswerState) -> Unsettled | None:
    """Step 4's reads on the slot's pinned `view`, no Git write: an unsafe listed path, a changed `.git*` file near
    them, or ignored files under them (listed). B's tree is read once: what each listed path was before."""
    rules = kind(admission.step).rules(admission.task.task_id)
    path = Path(admission.slot_path)
    unsafe = unsafe_path(files, path, rules, answer.paths, _base_files(view, base))
    dirt = view.worktree(path).dirty(base, ignored_under=attributes(rules, answer.paths))
    if unsafe is None:
        unsafe = git_file(dirt.tracked + dirt.untracked, rules, answer.paths)
    if unsafe is not None:  # the leftovers beside it are listed too, so one repeat can clear them all
        beside = sorted(set(dirt.tracked + dirt.untracked) - {unsafe, *answer.paths})
        return Unsettled("unsafe", bounded((unsafe, *beside)))
    return Unsettled("ignored", bounded(dirt.ignored)) if dirt.ignored else None


def _unwritten(checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str) -> Settled:
    """Nothing to commit is `nothing_written` only while HEAD is still B: a verifier racing this one may have committed
    the same index first, so a moved HEAD goes back to the adopt rule (its trailer commit) or `head_moved`."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    head = state.head
    if head is None or state.branch != task_branch(admission.task.task_id):
        return Unsettled("unborn" if head is None else "branch")
    if head == base:
        return Rejected("nothing_written")
    return Committed(head) if _ours(checkouts(state.root), head, base, admission) else _moved(checkouts(state.root), head, base, admission)


def _moved(repo: Repo, head: str, base: str, admission: Admission) -> Unsettled:
    """`head_moved`, listing the tags and branches that name a commit the agent made beside the moved HEAD (B excluded, the
    task's own branch excluded; annotated tags peeled to their commit). A ref whose commit is reachable from `main` or an
    `origin` ref can be the person's (the agent reset to `main`): never listed. The release does not remove any of them."""
    made = {head, *(each.sha for each in repo.history([head], not_on=[base]))}
    own = "refs/heads/" + task_branch(admission.task.task_id)
    theirs = [commit for each in repo.refs([MAIN, "refs/remotes/"]) if (commit := _peeled(repo, each.sha)) is not None]
    named = []
    for each in repo.refs(["refs/tags/", "refs/heads/"]):
        commit = _peeled(repo, each.sha)
        if each.name != own and commit in made and not any(repo.is_ancestor(commit, tip) for tip in theirs):
            named.append(each.name)
    return Unsettled("head_moved", bounded(named))


def _peeled(repo: Repo, sha: str) -> str | None:
    """The commit a ref's object names (an annotated tag is peeled); None when it names no commit."""
    tree = repo.tree(f"{sha}^{{commit}}")
    return None if tree is None else tree.sha


def git_file(dirty: tuple[str, ...], rules: StepRules, paths: tuple[str, ...]) -> str | None:
    """The first changed path with a component that starts with `.git` (any case: `.gitattributes`, `.gitignore`,
    `.gitmodules`, ...) sitting in a folder on the way to a listed path or under the step root: it would change how Git
    stages the listed paths, and status shows it but the agent may not commit it."""
    chain = {"/".join(path.split("/")[:depth]) for path in paths for depth in range(path.count("/") + 1)}
    for found in dirty:
        parts = found.split("/")
        for depth, part in enumerate(parts):
            folder = "/".join(parts[:depth])
            if dot_git(part) and (folder in chain or (folder + "/").startswith(rules.root)):
                return found
    return None


def _ours(repo: Repo, head: str, base: str, admission: Admission) -> bool:
    """H is exactly one commit beyond B whose message carries this attempt's trailer line: the factory's own commit."""
    found = repo.history([head], not_on=[base])
    return len(found) == 1 and found[0].sha == head and trailer(admission) in found[0].body.splitlines()


def _base_files(view: Repo, base: str) -> Mapping[str, tuple[str, str]]:
    tree = view.tree(f"{base}^{{commit}}")
    if tree is None or tree.sha != base:
        raise Unreadable("base")
    return tree.files


def secret(data: bytes) -> bool:
    """Bytes that look like a credential the sandbox may let the agent read: a PEM private key header, or a Codex login
    (`auth.json` holds both token names). A committed copy would be published to `origin`; no content of the person's own
    files is read to compare (tl-8bh9.14.50, docs/design/self-hosting-trial-5-fixes.md)."""
    key = b"-----BEGIN " in data and b"PRIVATE KEY-----" in data
    return key or (b'"access_token"' in data and b'"refresh_token"' in data)


def unsafe_path(
    files: SlotFiles, slot: Path, rules: StepRules, paths: tuple[str, ...], committed: Mapping[str, tuple[str, str]]
) -> str | None:
    """The first listed path that is not a plain regular file reached through plain directories: no component a symlink
    (`lstat` per component), no execute bit, at most `file_cap` bytes,
    readable by the factory and not a credential copy (`secret`); None when every one is safe. In `committed` (B's
    files) the path is absent or a 100644 file, and none of its folders is a file there (a symlink, gitlink or executable
    replaced by a plain file is a type change the step may not make). An absent listed path is a deletion only when the
    step may delete and it is a 100644 file in B reached through plain or absent directories; any other is unsafe."""
    for path in paths:
        parts = path.split("/")
        was = committed.get(path)
        if (was is not None and was[0] != MODE) or any("/".join(parts[:depth]) in committed for depth in range(1, len(parts))):
            return path
        folders = [files.lstat(slot.joinpath(*parts[:depth])) for depth in range(1, len(parts))]
        entry = files.lstat(slot.joinpath(*parts))
        if entry is None and rules.deletions and was is not None and all(each is None or each.kind == "dir" for each in folders):
            continue
        if not all(folder is not None and folder.kind == "dir" for folder in folders):
            return path
        if entry is None or entry.kind != "file" or entry.executable or entry.size > rules.file_cap:
            return path
        data = files.read(slot.joinpath(*parts), rules.file_cap)
        if data is None or secret(data):  # unreadable by the factory (mode 000: `git add` fails on it), or a credential copy
            return path
    return None


def clean_at(checkouts: Checkouts, files: SlotFiles, admission: Admission, commit: str) -> Path | Unsettled:
    """Step 6: the slot is on its task branch at X with nothing tracked or untracked left over (ignored files are not counted),
    returning the root its pointer names; leftovers are `uncommitted` with their listing, read fresh and never stored."""
    state = _observed(checkouts, files, admission)
    if isinstance(state, Unsettled):
        return state
    problem = state.problem(task_branch(admission.task.task_id), commit)
    if problem is None:
        return state.root
    if problem != "dirty":
        return Unsettled(problem)
    path = Path(admission.slot_path)
    return Unsettled("uncommitted", listing(checkouts(path, git_dir=state.gitdir), path))


def leftovers(
    checkouts: Checkouts, files: SlotFiles, admission: Admission, base: str, answer: AnswerState, end_commit: str | None
) -> Unsettled | None:
    """Read-only, for a person (`tl step show`): what a verify would report as a step to repeat, read now. Before the
    factory's commit the same `refusal` as `settle` (`unsafe`, `ignored`); after it, or for effect `keep`, the clean-tree
    check."""
    if answer.effect == "commit" and end_commit is None:
        state = _observed(checkouts, files, admission)
        if isinstance(state, Unsettled):
            return None
        if state.head is None or state.branch != task_branch(admission.task.task_id):  # as `settle` reports it
            return Unsettled("unborn" if state.head is None else "branch")
        if state.head != base:
            return None
        return refusal(checkouts(Path(admission.slot_path), git_dir=state.gitdir), files, admission, base, answer)
    found = clean_at(checkouts, files, admission, end_commit or base)
    return found if isinstance(found, Unsettled) else None
