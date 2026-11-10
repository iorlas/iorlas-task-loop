"""Read-only Git evidence for a stage's commit: the slot's pointer and state, and the verdict over (B, X, the one-step
chain, the plan blob).

Git only, through `git_porcelain`, plus the narrow file port for the slot's `.git` pointer: no Git write, process, lock,
ref, push or factory.db access. Identity, the worktree listing and every commit read run from the person's checkout (the
root the verified pointer names); only the status reads run on the slot. `GitUnavailable` and `Unreadable` propagate:
they mean unknown, never a verdict.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import Repo, Tree

from taskloop.plan_types import PLAN_NAME, Checkouts, Rejected, Rule, SlotFiles, StageRules, Verdict, Verified, path_allowed

type Problem = Literal["unborn", "branch", "head_moved", "dirty"]
MODE: Final = "100644"
POINTER_CAP: Final = 4096  # bytes of a `.git` pointer, `commondir` or `gitdir` file
LISTED: Final = 50  # leftover lines shown; the rest is counted
LINE_CAP: Final = 300  # characters of one leftover line
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

    def problem(self, at: str | None = None) -> Problem | None:
        """None when the slot is born, detached, clean and (given `at`) at that commit."""
        if self.head is None:
            return "unborn"
        if self.branch is not None:
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


def observe_slot(checkouts: Checkouts, files: SlotFiles, cwd: str, repo_id: str) -> SlotState | Literal["repo", "not_listed", "redirected"]:
    """The pointer check first (`redirected`, no Git call); then, from the root it names, `repo` when the repository is
    not `repo_id`, `redirected` when Git's common directory is not the one the pointer names, and `not_listed` when Git
    does not list the slot."""
    path = Path(cwd)
    found = pointer(files, path)
    if found is None:
        return "redirected"
    repo = checkouts(found.root)
    identity = repo.identity()
    if identity.key != repo_id:
        return "repo"
    if identity.common_dir != found.common:
        return "redirected"
    info = next((worktree for worktree in repo.worktrees() if worktree.path == path), None)
    if info is None:
        return "not_listed"
    return SlotState(found.root, info.head, info.branch, checkouts(path).worktree(path).dirty().raw)


def listing(repo: Repo, slot: Path) -> tuple[str, ...]:
    """The slot's leftovers as `XY path` lines from one porcelain status read, at most LISTED, then `+N more`, each made
    safe to print (`shown`): data for a person and a later repeat prompt, never parsed for control."""
    raw = repo.worktree_state(slot)
    records = () if raw is None else tuple(raw.decode("utf-8", "replace").split("\0"))
    lines: list[str] = []
    skip = False
    for record in records:
        if skip:
            skip = False
            continue
        kind, _, rest = record.partition(" ")
        fields = {"1": 7, "2": 8, "u": 9}.get(kind)
        if fields is not None:
            parts = rest.split(" ", fields)
            lines.append(f"{parts[0]} {parts[-1]}")
            skip = kind == "2"  # a rename's original path follows as its own record
        elif kind == "?":
            lines.append(f"?? {rest}")
    more = [f"+{len(lines) - LISTED} more"] if len(lines) > LISTED else []
    return (*(shown(line) for line in lines[:LISTED]), *more)


def shown(line: str) -> str:
    """A listing line safe to print: every control character (C0, DEL, C1: newlines, escapes, ANSI sequences) becomes
    `?`, and the line is cut at LINE_CAP characters. A path is agent-chosen data, never terminal input."""
    clean = "".join("?" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in line)
    return clean if len(clean) <= LINE_CAP else clean[: LINE_CAP - 3] + "..."


def judge(repo: Repo, root: Path, base: str, commit: str, rules: StageRules, paths: tuple[str, ...], *, unchanged: bool) -> Verdict:
    """The rules in order; the first broken one decides. Every read is of content-addressed objects. `unchanged`: X is
    B and only the plan rules apply to the plan at B (`reused`)."""
    plan_path = rules.root + PLAN_NAME
    tip = repo.tree(f"{commit}^{{commit}}")
    if tip is None or tip.sha != commit:  # never a tag, tree or abbreviation that resolves to some other commit
        return Rejected("commit_absent")
    if unchanged:
        return _plan(tip, plan_path, rules, reused=True)
    relation = repo.relate(base, commit)
    if relation.ahead != 0:
        return Rejected("not_descendant")
    if relation.behind != 1:
        return Rejected("chain_length")
    parent = repo.tree(f"{commit}^")
    if parent is None:
        raise Unreadable("parent")
    if parent.sha != base:  # one commit ahead, but its first parent is another: a merge brought B in
        return Rejected("not_descendant")
    broken = _changes(repo, root, tip, base, rules, paths)
    return Rejected(broken) if broken is not None else _plan(tip, plan_path, rules, reused=False)


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
