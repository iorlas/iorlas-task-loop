"""Read-only Git evidence for a stage's commits: the slot's pointer and state, and the verdict over the step's chain
(attempt 1's B, each attempt's commit, the plan blob at the last).

Git only, through `git_porcelain`, plus the narrow file port for the slot's `.git` pointer: no Git write, process, lock,
ref, push or factory.db access. Identity, the worktree listing and every commit read run from the person's checkout (the
root the verified pointer names); only the status reads run on the slot. `GitUnavailable` and `Unreadable` propagate:
they mean unknown, never a verdict.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import GitUnavailable, Repo, Tree

from taskloop.plan_types import PLAN_NAME, Checkouts, Rejected, Rule, SlotFiles, StageRules, StepAttempt, Verdict, Verified, path_allowed

type Problem = Literal["unborn", "branch", "head_moved", "dirty"]
MODE: Final = "100644"
POINTER_CAP: Final = 4096  # bytes of a `.git` pointer, `commondir` or `gitdir` file
LISTED: Final = 50  # leftover lines shown; the rest is counted
LINE_CAP: Final = 300  # characters of one leftover line
ORIGINAL: Final = "R<"  # a status record of a rename's original path (staged, never listed)
GITDIR: Final = re.compile(r"gitdir:\s*(.+)")  # git_porcelain's `real_env.git_dir` rule


class Unreadable(Exception):
    """A read that cannot be told apart from a failure returned nothing: the parent of X, a listed blob, or a listed
    path's entry. The library reads these with an unchecked exit code, so None is never taken as evidence."""


@dataclass(frozen=True)
class SlotState:
    root: Path
    head: str | None
    branch: str | None
    dirty: bool

    def problem(self, branch: str, at: str | None = None) -> Problem | None:
        """None when the slot is born, on exactly `branch` (its task branch), clean and (given `at`) at that commit;
        `branch` when it is detached or on any other branch."""
        if self.head is None:
            return "unborn"
        if self.branch != branch:
            return "branch"
        if at is not None and self.head != at:
            return "head_moved"
        return "dirty" if self.dirty else None


def _small(files: SlotFiles, path: Path) -> str | None:
    data = files.read(path, POINTER_CAP)
    try:
        return None if data is None else data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


@dataclass(frozen=True)
class Pointer:
    """The linked Git directory and the common Git directory a slot's `.git` names, both as Git resolves them."""

    gitdir: Path
    common: Path

    @property
    def root(self) -> Path:
        """git_porcelain's `RepoIdentity.root` rule: the common directory's parent when it is named `.git`."""
        return self.common.parent if self.common.name == ".git" else self.common


def pointer(files: SlotFiles, slot: Path) -> Pointer | None:
    """What `<slot>/.git` names, judged with the resolution Git and git_porcelain's pin use (`(slot / text).resolve()`,
    `(G / commondir).resolve()`), never a lexical one: the slot path itself has no symlink; `.git` is a regular gitdir
    file; G resolves outside the slot to a directory directly under `<C>/worktrees`, C (from `G/commondir`) also outside
    the slot; and G's back-pointer `G/gitdir` resolves to exactly `<slot>/.git`. G and C must also resolve to the very
    path written (no symlink on the way, so no agent-made link can steer them). Else None (`redirected`). Relative
    pointers (`git worktree add --relative-paths`) resolve against the slot and G as Git resolves them. Plain reads only:
    a directory, symlink or FIFO at `.git` is refused before any open. The library re-reads `.git` on each later Git
    call: a swap after this check is the named residual (design section 4)."""
    if files.resolve(slot) != slot:
        return None
    dotgit = slot / ".git"
    entry = files.lstat(dotgit)
    text = _small(files, dotgit) if entry is not None and entry.kind == "file" and entry.size <= POINTER_CAP else None
    found = None if text is None else GITDIR.fullmatch(text)
    named = None if found is None else slot / found[1].strip()
    gitdir = None if named is None else files.resolve(named)
    if named is None or gitdir is None or gitdir != Path(os.path.normpath(named)) or gitdir.is_relative_to(slot):
        return None  # through no symlink at all: the path as written is the path Git resolves
    listed = files.lstat(gitdir)
    common = _small(files, gitdir / "commondir") if listed is not None and listed.kind == "dir" else None
    shared = None if common is None else files.resolve(gitdir / common)
    lexical = None if common is None else Path(os.path.normpath(gitdir / common))
    if shared is None or shared != lexical or shared.is_relative_to(slot) or gitdir.parent != shared / "worktrees":
        return None
    back = _small(files, gitdir / "gitdir")
    return Pointer(gitdir, shared) if back is not None and files.resolve(gitdir / back) == dotgit else None


def _repository(checkouts: Checkouts, files: SlotFiles, path: Path, repo_id: str) -> tuple[Repo, Path] | Literal["repo", "redirected"]:
    """The pointer check first (`redirected`, no Git call); then, from the root it names, `repo` when the repository is
    not `repo_id`, `redirected` when Git's common directory is not the one the pointer names. The view and its root."""
    found = pointer(files, path)
    if found is None:
        return "redirected"
    repo = checkouts(found.root)
    identity = repo.identity()
    if identity.key != repo_id:
        return "repo"
    return (repo, found.root) if identity.common_dir == found.common else "redirected"


def repository(checkouts: Checkouts, files: SlotFiles, cwd: str, repo_id: str) -> Path | Literal["repo", "redirected"]:
    """The person's checkout (the root a verified slot pointer names) of the repository `repo_id`: the first half of
    `observe_slot`, for a caller that then works on the repository, never on the slot."""
    found = _repository(checkouts, files, Path(cwd), repo_id)
    return found if isinstance(found, str) else found[1]


def observe_slot(checkouts: Checkouts, files: SlotFiles, cwd: str, repo_id: str) -> SlotState | Literal["repo", "not_listed", "redirected"]:
    """`repository`'s checks, then `not_listed` when Git does not list the slot."""
    path = Path(cwd)
    found = _repository(checkouts, files, path, repo_id)
    if isinstance(found, str):
        return found
    repo, root = found
    info = next((worktree for worktree in repo.worktrees() if worktree.path == path), None)
    if info is None:
        return "not_listed"
    return SlotState(root, info.head, info.branch, checkouts(path).worktree(path).dirty().raw)


def _status(repo: Repo, slot: Path) -> tuple[tuple[str, str], ...] | None:
    """One porcelain v2 status read of the slot as (XY, path) records: `??` for untracked, a rename's original path as
    its own `R` record; None when Git cannot read the slot."""
    raw = repo.worktree_state(slot)
    if raw is None:
        return None
    found: list[tuple[str, str]] = []
    renamed = False
    for record in raw.decode("utf-8", "replace").split("\0"):
        if renamed:
            found.append((ORIGINAL, record))  # its deletion is staged with the rename; not a listing line of its own
            renamed = False
            continue
        kind, _, rest = record.partition(" ")
        fields = {"1": 7, "2": 8, "u": 9}.get(kind)
        if fields is not None:
            parts = rest.split(" ", fields)
            found.append((parts[0], parts[-1]))
            renamed = kind == "2"
        elif kind == "?":
            found.append(("??", rest))
    return tuple(found)


def listing(repo: Repo, slot: Path) -> tuple[str, ...]:
    """The slot's leftovers as `XY path` lines from one porcelain status read, `bounded`: data for a person and a
    repeat's feedback, never parsed for control."""
    return bounded(f"{code} {path}" for code, path in _status(repo, slot) or () if code != ORIGINAL)


def staged(repo: Repo, slot: Path) -> tuple[str, ...]:
    """The paths whose index entry differs from HEAD (staged changes, renames' both sides), from one status read; Git
    unable to read the slot is GitUnavailable, never an empty index."""
    found = _status(repo, slot)
    if found is None:
        raise GitUnavailable("The slot's status is unreadable")
    return tuple(path for code, path in found if code[0] not in ".?")


def bounded(lines: Iterable[str]) -> tuple[str, ...]:
    """The one listing shape for a person and an agent: every line `shown`, at most LISTED, then `+K more` with the true
    count of the lines left out. Applied once, where a listing is made."""
    found = list(lines)
    more = [f"+{len(found) - LISTED} more"] if len(found) > LISTED else []
    return (*(shown(line) for line in found[:LISTED]), *more)


def shown(line: str) -> str:
    """A listing line safe to print: every control character (C0, DEL, C1: newlines, escapes, ANSI sequences) becomes
    `?`, and the line is cut at LINE_CAP characters. A path is agent-chosen data, never terminal input."""
    clean = "".join("?" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in line)
    return clean if len(clean) <= LINE_CAP else clean[: LINE_CAP - 3] + "..."


def judge(repo: Repo, root: Path, commit: str, rules: StageRules, steps: tuple[StepAttempt, ...]) -> Verdict:
    """The rules in order over the step's chain; the first broken one decides. Every read is of content-addressed
    objects. S: each earlier `planned` attempt's stored X, then `commit` (Xn) when the last attempt is `planned`. Xn is
    len(S) first-parent commits on attempt 1's B, each S_k one commit on S_k-1 judged against its own attempt's `paths`;
    then the plan rules at Xn. No commit in the whole step (`commit` is B1): only the plan rules, `reused`. Attempt 1
    alone is the one-step chain."""
    plan_path = rules.root + PLAN_NAME
    tip = repo.tree(f"{commit}^{{commit}}")
    if tip is None or tip.sha != commit:  # never a tag, tree or abbreviation that resolves to some other commit
        return Rejected("commit_absent")
    *earlier, last = steps
    chain = [(each.plan_commit, each.paths) for each in earlier if each.disposition == "planned" and each.plan_commit is not None]
    chain += [(commit, last.paths)] if last.disposition == "planned" else []
    if not chain:
        return _plan(tip, plan_path, rules, reused=True)
    parent = steps[0].base_commit
    relation = repo.relate(parent, commit)
    if relation.ahead != 0:
        return Rejected("not_descendant")
    if relation.behind != len(chain):
        return Rejected("chain_length")
    for sha, paths in chain:
        broken = _link(repo, root, sha, parent, rules, paths)
        if broken is not None:
            return Rejected(broken)
        parent = sha
    return _plan(tip, plan_path, rules, reused=False)


def _link(repo: Repo, root: Path, sha: str, parent: str, rules: StageRules, paths: tuple[str, ...]) -> Rule | None:
    """One commit of the chain: a commit whose first parent is `parent` (else a merge brought it in), its changes held
    to its own attempt's listed `paths`."""
    tree = repo.tree(f"{sha}^{{commit}}")
    if tree is None or tree.sha != sha:
        return "commit_absent"
    up = repo.tree(f"{sha}^")
    if up is None:
        raise Unreadable("parent")
    if up.sha != parent:
        return "not_descendant"
    return _changes(repo, root, tree, parent, rules, paths)


def _changes(repo: Repo, root: Path, tip: Tree, base: str, rules: StageRules, paths: tuple[str, ...]) -> Rule | None:
    """One diff B..X: each change added or modified (deletions only when the stage allows them), on an allowed path the
    answer listed, mode 100644, and every committed blob at most `file_cap` bytes after the full read."""
    for change in repo.worktree(root).diff(base, tip.sha, cap=0).changes:
        if (change.kind == "D" and not rules.deletions) or not path_allowed(change.path, rules) or change.path not in paths:
            return "paths"
        if change.kind == "D":
            continue
        entry = tip.files.get(change.path)
        if entry is None:
            raise Unreadable("entry")
        if entry[0] != MODE:
            return "mode"
        data = tip.read(change.path)
        if data is None:
            raise Unreadable("blob")
        if len(data) > rules.file_cap:
            return "file_size"
    return None


def _plan(tip: Tree, plan_path: str, rules: StageRules, *, reused: bool) -> Verdict:
    """The plan at X passes the path and mode rules and the content floor; never a review of what it says."""
    if not path_allowed(plan_path, rules):
        return Rejected("paths")
    entry = tip.files.get(plan_path)
    if entry is None:
        return Rejected("plan_missing")
    if entry[0] != MODE:
        return Rejected("mode")
    data = tip.read(plan_path)
    if data is None:  # the listing has the plan: an empty read is a failed read
        raise Unreadable("blob")
    broken = _content(data, rules.file_cap)
    return Verified(entry[1], reused) if broken is None else Rejected(broken)


def _content(data: bytes, cap: int) -> Rule | None:
    """Strict UTF-8, not whitespace only, at most `cap` bytes after the full read."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "plan_encoding"
    if not text.strip():
        return "plan_empty"
    return "plan_size" if len(data) > cap else None
