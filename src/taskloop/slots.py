"""Managed slots: adoption (the only `slot` writer) and typed free/held/unknown observation; no reservation writer."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from git_porcelain import GitUnavailable, Repo, WorktreeInfo

from taskloop.plan_schema import SLOT, current, marks
from taskloop.repo import RepoId

type Unknown = Literal["not_listed", "main", "dirty", "git_unavailable", "store_unavailable"]
type Unadoptable = Unknown | Literal["other_root", "inside_checkout"]


@dataclass(frozen=True)
class SlotView:
    """Built only by `observe`; callers never supply a slot path."""

    name: str
    path: Path
    state: Literal["free", "held", "unknown"]
    reason: Unknown | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class Adopted:
    name: str
    path: Path


@dataclass(frozen=True)
class NotAdopted:
    name: str
    reason: Unadoptable


class SlotsUnavailable(Exception):
    """The slot rows themselves could not be read, so no slot is known (none is free)."""


def slot_names(count: int) -> tuple[str, ...]:
    if count < 1:
        raise ValueError("A slot count of at least 1 is required")
    return tuple(f"s{number}" for number in range(1, count + 1))


def _order(name: str) -> tuple[int, str]:
    return len(name), name


def _clean(repo: Repo, listed: tuple[WorktreeInfo, ...], path: Path) -> Unknown | None:
    """None when Git lists a non-main worktree at exactly `path` and its one status read is clean."""
    info = next((worktree for worktree in listed if worktree.path == path), None)
    if info is None:
        return "not_listed"
    if info.is_main:
        return "main"
    try:
        return "dirty" if repo.worktree(path).dirty().raw else None
    except GitUnavailable:
        return "git_unavailable"


def _adopted(con: sqlite3.Connection, repo_id: str) -> dict[str, str]:
    rows: list[tuple[str, str]] = con.execute("SELECT name,cwd FROM slot WHERE repo_id=?", (repo_id,)).fetchall()
    return dict(rows)


def adopt(
    connect: Callable[[], sqlite3.Connection | None],
    begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
    repo: Repo,
    root: Path,
    count: int,
) -> tuple[Adopted | NotAdopted, ...]:
    """Record `s1..sN` at `<root>/<repo_id>/<name>` once Git lists each as a clean linked worktree; idempotent.

    A name already adopted under another root is reported as `other_root`, never moved; a root inside the main checkout
    is refused, so no slot lives in the person's checkout.
    """
    names = slot_names(count)
    try:
        repo_id = repo.identity().key
        con = connect()
        if con is None or not current(con):
            return tuple(NotAdopted(name, "store_unavailable") for name in names)
        known = _adopted(con, repo_id)
        pending = [name for name in names if name not in known]
        listed = repo.worktrees() if pending else ()
    except GitUnavailable:
        return tuple(NotAdopted(name, "git_unavailable") for name in names)
    except sqlite3.Error:
        return tuple(NotAdopted(name, "store_unavailable") for name in names)
    base = root.resolve() / repo_id
    refused = _refusals(repo, listed, base, pending)
    accepted = [name for name in pending if name not in refused]
    if accepted:
        try:
            with begin(con):
                for name in accepted:
                    con.execute(f"INSERT OR IGNORE INTO slot ({SLOT}) VALUES ({marks(SLOT)})", (repo_id, name, str(base / name)))
                known = _adopted(con, repo_id)
        except sqlite3.Error:
            for name in accepted:
                refused[name] = "store_unavailable"
    return tuple(_result(name, base, known, refused) for name in names)


def _refusals(repo: Repo, listed: tuple[WorktreeInfo, ...], base: Path, pending: list[str]) -> dict[str, Unadoptable]:
    main = next((worktree.path for worktree in listed if worktree.is_main), None)
    if main is not None and base.is_relative_to(main.resolve()):
        return dict.fromkeys(pending, "inside_checkout")
    return {name: reason for name in pending if (reason := _clean(repo, listed, base / name)) is not None}


def _result(name: str, base: Path, known: dict[str, str], refused: dict[str, Unadoptable]) -> Adopted | NotAdopted:
    if name in refused:
        return NotAdopted(name, refused[name])
    if name not in known:
        return NotAdopted(name, "store_unavailable")
    return Adopted(name, base / name) if Path(known[name]) == base / name else NotAdopted(name, "other_root")


def observe(con: sqlite3.Connection, repo: Repo, repo_id: RepoId) -> tuple[SlotView, ...]:
    """Every adopted slot of the repo, lowest name first; store or Git failure never yields `free`."""
    try:
        slots = sorted(_adopted(con, repo_id).items(), key=lambda item: _order(item[0]))
    except sqlite3.Error as error:
        raise SlotsUnavailable("Slot rows unavailable") from error
    try:
        rows: list[tuple[str, str]] = con.execute("SELECT slot,attempt_id FROM reservation WHERE repo_id=?", (repo_id,)).fetchall()
    except sqlite3.Error:
        return tuple(SlotView(name, Path(cwd), "unknown", "store_unavailable") for name, cwd in slots)
    held = dict(rows)
    listed: tuple[WorktreeInfo, ...] | None = None
    if any(name not in held for name, _cwd in slots):
        try:
            listed = repo.worktrees()
        except GitUnavailable:
            listed = None
    views: list[SlotView] = []
    for name, cwd in slots:
        path = Path(cwd)
        if name in held:
            views.append(SlotView(name, path, "held", attempt_id=held[name]))
            continue
        reason: Unknown | None = "git_unavailable" if listed is None else _clean(repo, listed, path)
        views.append(SlotView(name, path, "free") if reason is None else SlotView(name, path, "unknown", reason))
    return tuple(views)
