"""Read-only Git evidence of a slot: its pointer and state, its leftovers listing and its staged paths; the verdict over
a step's chain is `verdict`'s.

Git only, through `git_porcelain`, plus the narrow file port for the slot's `.git` pointer: no Git write, process, lock,
ref, push or factory.db access. Identity and the worktree listing run from the person's checkout (the root the verified
pointer names); only the status reads run on the slot. `GitUnavailable` propagates: it means unknown, never a verdict.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import GitUnavailable, Repo

from taskloop.attempt_types import Checkouts, SlotFiles

type Problem = Literal["unborn", "branch", "head_moved", "dirty"]
POINTER_CAP: Final = 4096  # bytes of a `.git` pointer, `commondir` or `gitdir` file
LISTED: Final = 50  # leftover lines shown; the rest is counted
LINE_CAP: Final = 300  # characters of one leftover line
ORIGINAL: Final = "R<"  # a status record of a rename's original path (staged, never listed)
GITDIR: Final = re.compile(r"gitdir:\s*(.+)")  # git_porcelain's `real_env.git_dir` rule


@dataclass(frozen=True)
class SlotState:
    """The slot as Git lists it, from the root its verified pointer names; `gitdir` is that pointer's Git directory,
    which every later Git view of the slot is pinned to (`Checkouts`' `git_dir`)."""

    root: Path
    head: str | None
    branch: str | None
    dirty: bool
    gitdir: Path

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
    a directory, symlink or FIFO at `.git` is refused before any open. Every later Git view of the slot is pinned to the
    G returned here (`Checkouts`' `git_dir`), so a pointer swapped after this check is never followed (design section
    4(a))."""
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


def _repository(checkouts: Checkouts, files: SlotFiles, path: Path, repo_id: str) -> tuple[Repo, Pointer] | Literal["repo", "redirected"]:
    """The pointer check first (`redirected`, no Git call); then, from the root it names, `repo` when the repository is
    not `repo_id`, `redirected` when Git's common directory is not the one the pointer names. The view and the pointer."""
    found = pointer(files, path)
    if found is None:
        return "redirected"
    repo = checkouts(found.root)
    identity = repo.identity()
    if identity.key != repo_id:
        return "repo"
    return (repo, found) if identity.common_dir == found.common else "redirected"


def repository(checkouts: Checkouts, files: SlotFiles, slot_path: str, repo_id: str) -> Path | Literal["repo", "redirected"]:
    """The person's checkout (the root a verified slot pointer names) of the repository `repo_id`: the first half of
    `observe_slot`, for a caller that then works on the repository, never on the slot."""
    found = _repository(checkouts, files, Path(slot_path), repo_id)
    return found if isinstance(found, str) else found[1].root


def observe_slot(
    checkouts: Checkouts, files: SlotFiles, slot_path: str, repo_id: str
) -> SlotState | Literal["repo", "not_listed", "redirected"]:
    """`repository`'s checks, then `not_listed` when Git does not list the slot."""
    path = Path(slot_path)
    found = _repository(checkouts, files, path, repo_id)
    if isinstance(found, str):
        return found
    repo, named = found
    info = next((worktree for worktree in repo.worktrees() if worktree.path == path), None)
    if info is None:
        return "not_listed"
    dirty = checkouts(path, git_dir=named.gitdir).worktree(path).dirty().raw
    return SlotState(named.root, info.head, info.branch, dirty, named.gitdir)


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
