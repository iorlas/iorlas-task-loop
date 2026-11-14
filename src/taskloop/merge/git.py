"""Merge Git effects and structural checks through the owning shelf API."""

from git_porcelain import BranchHeld, RefMoved, Repo, Worktree

from taskloop.attempt_types import TRAILER, SlotFiles, StepRules, dot_git
from taskloop.factory_commit import unsafe_path
from taskloop.merge.models import Answer, Reason, Terminal, Work

SOURCE = "Task-Loop-Merge-Start"
TARGET = "Task-Loop-Merge-Target"


def message(work: Work) -> str:
    return (f"Merge current main into {work.task_id}\n\n{TRAILER}: {work.attempt_id}"
            f"\n{SOURCE}: {work.source}\n{TARGET}: {work.target}")


def completed(repo: Repo, head: str, work: Work) -> bool:
    """A completed action after a crash must have exactly the recorded parents and provenance."""
    first, second, third = (repo.tree(f"{head}^{n}") for n in (1, 2, 3))
    history = repo.history([head], limit=1)
    return (first is not None and first.sha == work.source and second is not None and second.sha == work.target
            and third is None and bool(history) and history[0].body.strip() == message(work).partition("\n\n")[2])


def attach(repo: Repo, slot: Worktree, work: Work) -> Terminal | None:
    """CAS then normal branch take; adopt either action after a crash, never overwrite another writer."""
    if work.branch is None or any(info.path == work.slot and info.branch == work.branch and info.head == work.result
                                  for info in repo.worktrees()):
        return None
    result = work.result or work.source
    ref = f"refs/heads/{work.branch}"
    tip = next((entry.sha for entry in repo.refs([ref]) if entry.name == ref), None)
    if tip not in (work.source, result):
        return Terminal(reason=Reason.MOVED, explanation="The task branch moved during preparation; the retained result is reserved.")
    if any(info.branch == work.branch and info.path != work.slot for info in repo.worktrees()):
        return Terminal(reason=Reason.MOVED, explanation="Another checkout took the task branch during preparation; its work is retained.")
    if tip != result:
        moved = repo.update_ref(ref, result, expected=tip)
        if isinstance(moved, RefMoved):
            return Terminal(reason=Reason.MOVED, explanation="The task branch changed before the prepared result could be attached.")
    taken = slot.take_branch(work.branch, result, mode="resume")
    if isinstance(taken, BranchHeld) or taken.head != result:
        return Terminal(reason=Reason.MOVED, explanation="The task branch changed while taking the prepared result; preparation stopped.")
    return None


def supported(repo: Repo, work: Work) -> bool:
    """Only bounded regular UTF-8 text conflicts; automatic changes are left untouched."""
    for commit in (work.source, work.target):
        tree = None if commit is None else repo.tree(commit)
        if tree is None:
            return False
        for path in work.conflicts:
            if unsafe_name(path):
                return False
            if path not in tree.files:  # a textual deletion conflict
                continue
            data = tree.read(path)
            if tree.files[path][0] != "100644" or data is None or len(data) > 1 << 20 or b"\0" in data:
                return False
            try:
                data.decode("utf-8")
            except UnicodeError:
                return False
    return True


def unsafe_name(path: str) -> bool:
    parts = path.split("/")
    return (not path or path.startswith("/") or any(part in ("", ".", "..", ".beads") or dot_git(part) for part in parts))


def accepted(repo: Repo, slot: Worktree, files: SlotFiles, work: Work, answer: Answer) -> str | None:
    """Validate the agent's changes against the captured automatic merge, never against either side alone."""
    baseline = None if work.baseline is None else repo.tree(work.baseline)
    if baseline is None:
        return "The automatic merge's recorded tree is unavailable."
    initial = _paths(files, work, answer)
    if initial is not None:
        return initial
    bad = unsafe_path(files, work.slot, StepRules(root="", max_paths=96, deletions=True), answer.paths, baseline.files)
    if bad is not None:
        return f"The resolution contains an unsafe edit: {bad.path!r}: {bad.explanation}"
    tree = repo.tree(str(slot.capture()))
    if tree is None:
        return "The resolution's working tree is unavailable."
    changed = {path for path in set(baseline.files) | set(tree.files) if baseline.files.get(path) != tree.files.get(path)}
    if changed != set(answer.paths):
        return "The resolution paths do not account for its edits; automatic merge changes must be retained."
    slot.stage(answer.paths)
    return "The merge index still has unresolved paths." if slot.unmerged() else None


def _paths(files: SlotFiles, work: Work, answer: Answer) -> str | None:
    if len(answer.paths) > 96 or len(set(answer.paths)) != len(answer.paths) or any(unsafe_name(path) for path in answer.paths):
        return "The resolution declared unsafe or duplicate paths."
    for path in work.conflicts:
        data = files.read(work.slot / path, 1 << 20)
        if data is not None and any(line.startswith((b"<<<<<<<", b"=======", b">>>>>>>")) for line in data.splitlines()):
            return f"Conflict markers remain in {path}."
    return None
