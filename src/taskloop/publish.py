"""Publish a verified plan: push the attempt's verified commit X to origin's `task/<id>`, never forced, and record the
published fact (`published_branch`, its one writer). Its one Git write is `push`.

Before any network call, in order (section 3 of tl-8bh9.4.3.1.12): the attempt exists, is not abandoned, is not already
published (then no Git at all), has a stored `verified` verdict with X; the slot's pointer names the attempt's repository
(file reads first); `origin` exists; the local `task/<id>` contains X. Then one non-force push of the pinned X from the
person's checkout (never the slot, which another attempt may hold: no reservation, slot lock or stop proof is needed, as
the push touches no worktree, index or HEAD). Only a `Pushed` result is recorded, in one fenced transaction (Git itself
then confirmed the push target holds X); pending is derived. A rejected push is classified with one `ls_remote` for its
refusal word only: that reads the fetch URL, which a `pushurl`/`pushInsteadOf` may make another repository than the
push target, so it never records anything. Nothing fetches, forces or deletes a remote ref. No Git output, remote
URL or credential is printed or stored: `detail` is fixed text plus shas.

Everything is injected: the store, the remote-capable Git views (`remotes`: hooks off, a bounded transport timeout), the
slot file port and the clock. It imports neither `operations` nor `repeat` (the entry's import closure).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import (
    GitReadFailure,
    GitUnavailable,
    HookRejected,
    MissingRemote,
    MissingRevision,
    Pushed,
    RefRejected,
    Repo,
    Sha,
    Transient,
)

from taskloop.attempt_reads import PublishedRow, StoreUnavailable, as_nullable_text, as_text
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, SlotFiles
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import BLOCKED, ActionKind, Reason
from taskloop.factory_schema import LATER, PUBLISHED, current, marks
from taskloop.prepare import task_branch
from taskloop.slot_state import repository

REMOTE: Final = "origin"  # v1: the one remote (owner decision); never stored
NOTHING: Final = "Nothing was pushed or recorded."
ROW: Final = """SELECT p.task_id,p.repo_id,p.end_commit,s.path,v.verdict,v.reason,x.claim,b.commit_sha,b.remote_head,b.published_at
FROM attempt p LEFT JOIN verification v ON v.attempt_id=p.attempt_id
LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id LEFT JOIN published_branch b ON b.attempt_id=p.attempt_id
LEFT JOIN slot s ON s.repo_id=p.repo_id AND s.name=p.slot
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""
# Inside the write transaction: still verified at X, not abandoned, still the task's current attempt.
FENCE: Final = """SELECT 1 FROM attempt p JOIN verification v ON v.attempt_id=p.attempt_id
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND v.verdict='verified' AND p.end_commit=?
AND NOT EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id AND x.claim<>'kept')
AND NOT """ + LATER
ABANDONED: Final = "SELECT 1 FROM slot_release WHERE attempt_id=? AND claim<>'kept'"


@dataclass(frozen=True)
class BranchPublished:
    """This call recorded the publication: X pushed, and `remote_head` the tip the push confirmed (X itself)."""

    commit: str
    remote_head: str


@dataclass(frozen=True)
class NotPublished:
    """A refusal (exit 1) or an unknown (exit 3, rerun); the remote changed only if `detail` says so."""

    kind: Literal["refused", "unavailable"]
    reason: str
    detail: str = NOTHING

    @property
    def word(self) -> str:
        return f"{self.kind}:{self.reason}"


type PublishResult = BranchPublished | PublishedRow | NotPublished


PUBLISHED_WORDS: Final = ("published", "already_published")


def is_published(word: str) -> bool:
    """Whether a `publish_word` (or a log's `branch=` word) says the branch is on `origin`."""
    return word in PUBLISHED_WORDS


def publish_word(result: PublishResult) -> str:
    """The one word for a log line, a status or a result: `published` (this call pushed it), `already_published` (it was
    before), `refused:<reason>` or `unavailable:<reason>`."""
    if isinstance(result, NotPublished):
        return result.word
    return "published" if isinstance(result, BranchPublished) else "already_published"


@dataclass(frozen=True)
class _Row:
    task_id: str
    repo_id: str
    commit: str | None  # X, the verified commit (B itself for `reused`)
    slot_path: str | None  # the adopted slot's path; the reservation may already be released
    verdict: str | None
    reason: str | None  # a rejected verdict's rule
    abandoned: bool
    published: PublishedRow | None


def _already(values: tuple[object, ...]) -> PublishedRow:
    """A stored `published_branch` row: (commit_sha, remote_head, published_at)."""
    if not isinstance(values[2], (int, float)):
        raise StoreUnavailable("Malformed publication time")
    return PublishedRow(as_text(values[0]), as_text(values[1]), float(values[2]))


def _row(row: tuple[object, ...]) -> _Row:
    published = None if row[7] is None else _already(row[7:10])
    abandoned = row[6] is not None and as_text(row[6]) != "kept"  # an abandon never keeps the claim
    return _Row(as_text(row[0]), as_text(row[1]), as_nullable_text(row[2]), as_nullable_text(row[3]), as_nullable_text(row[4]),
                as_nullable_text(row[5]), abandoned, published)


def _refused(reason: str, detail: str) -> NotPublished:
    return NotPublished("refused", reason, f"{detail} {NOTHING}")


def _unavailable(reason: str, detail: str) -> NotPublished:
    return NotPublished("unavailable", reason, f"{detail} {NOTHING}")


@dataclass(frozen=True)
class BranchPublish:
    store: AttemptStore
    remotes: Checkouts
    slot_files: SlotFiles
    clock: Callable[[], float]

    def publish(self, key: AttemptKey) -> PublishResult:
        try:
            with operation(self.store, ActionKind.FINALIZE, subject=key.attempt_id,
                           existing=lambda owner: self.store.owns_entry(key, owner)) as call:
                result = self._publish(key)
                call.resolved = not isinstance(result, NotPublished) or result.kind != "unavailable"
                return result
        except Fenced:
            return _refused(Reason.DRAINING, BLOCKED)
        except Unobservable:
            return _unavailable("observe", "The calling process cannot be observed.")
        except (sqlite3.Error, StoreUnavailable):
            return _unavailable("store", "The factory database is unavailable.")

    def _publish(self, key: AttemptKey) -> PublishResult:
        """Publish the attempt's verified commit once: every precondition first, then one push, then the record."""
        try:
            row = self._read(key)
        except (sqlite3.Error, StoreUnavailable) as error:
            return _unavailable("store", f"{type(error).__name__}.")
        if not isinstance(row, _Row):
            return row
        x = row.commit or ""
        try:
            found = self._repository(row, x)
        except GitUnavailable as error:
            return _unavailable("git", f"Git could not read the repository ({type(error).__name__}).")
        return found if isinstance(found, NotPublished) else self._pushed(key, row.task_id, *found, x)

    def _read(self, key: AttemptKey) -> _Row | PublishResult:
        """Its own fenced read, in order: the attempt, not abandoned, not yet published (then no Git), verified."""
        con = self.store.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        found: tuple[object, ...] | None = con.execute(ROW, astuple(key)).fetchone()
        if found is None:
            return _refused("absent", "No such attempt.")
        row = _row(found)
        if row.published is not None and not row.abandoned:
            return row.published
        return self._refusal(row) or row

    @staticmethod
    def _refusal(row: _Row) -> NotPublished | None:
        """Read before any Git call: not abandoned, a stored `verified` verdict with its commit."""
        if row.abandoned:
            return _refused("abandoned", "The attempt was abandoned; a fresh start publishes its own result.")
        if row.verdict == "verified" and row.commit is not None:
            return None
        if row.verdict == "rejected":
            return _refused("not_verified", f"The step's result was rejected ({row.reason}).")
        return _refused("not_verified", "The step's result is not verified yet: `tl step verify`.")

    def _repository(self, row: _Row, x: str) -> tuple[Repo, Path] | NotPublished:
        """The person's checkout through the slot's verified pointer (file reads first), `origin`, then the local branch
        rule: `task/<id>` exists and contains X. Git calls run on the checkout only, never on the slot."""
        if row.slot_path is None:
            return _refused("repository", "The attempt's slot is not adopted.")
        root = repository(self.remotes, self.slot_files, row.slot_path, row.repo_id)
        if isinstance(root, str):
            return _refused("repository", f"The slot's pointer or repository is not the attempt's ({root}): inspect the slot.")
        repo = self.remotes(root)
        try:
            repo.remote_url(REMOTE)  # a presence check only: the URL is never kept, logged or printed
        except MissingRemote:
            return _refused("no_remote", f"The repository has no `{REMOTE}` remote: `git remote add {REMOTE} ...`, then rerun.")
        name = "refs/heads/" + task_branch(row.task_id)
        tip = next((entry.sha for entry in repo.refs(["refs/heads/task/"]) if entry.name == name), None)
        if tip is None or not repo.is_ancestor(x, tip):
            return _refused("branch_moved", f"The local {task_branch(row.task_id)} is missing or does not contain {x}: restore it, "
                            "then rerun (or abandon).")
        return repo, root

    def _pushed(self, key: AttemptKey, task_id: str, repo: Repo, root: Path, x: str) -> PublishResult:
        """One non-force push of the pinned X; no Git output is kept."""
        branch = task_branch(task_id)
        try:
            pushed = repo.worktree(root).push(branch, remote=REMOTE, head=Sha(x))
        except GitUnavailable as error:
            return _unavailable("git", f"Git could not push ({type(error).__name__}): check `git push` works from this shell, rerun.")
        if isinstance(pushed, Pushed):
            return self._record(key, x)
        if isinstance(pushed, RefRejected):
            return _rejected(repo, branch, x)
        if isinstance(pushed, Transient):
            return _unavailable("remote", f"`{REMOTE}` could not be reached (network or credentials): rerun.")
        if isinstance(pushed, HookRejected):
            return _unavailable("git", "A hook refused the push although hooks are off: rerun.")
        return _refused("remote_rejected", _policy(repo, branch, x))

    def _record(self, key: AttemptKey, x: str) -> PublishResult:
        """After `Pushed` only, one fenced transaction: the published row in, once; a lost fence records nothing (the
        remote keeps X)."""
        pushed = f"{REMOTE} holds {x}; nothing was recorded"
        try:
            con = self.store.connect()
            if con is None or not current(con):
                raise StoreUnavailable("Factory database unavailable or incompatible")
            with self.store.begin(con):
                existing = con.execute("SELECT commit_sha,remote_head,published_at FROM published_branch WHERE attempt_id=?",
                                       (key.attempt_id,)).fetchone()
                if existing is not None:
                    return _already(existing)
                if con.execute(FENCE, (*astuple(key), x)).fetchone() is None:
                    gone = con.execute(ABANDONED, (key.attempt_id,)).fetchone() is not None
                    return NotPublished("refused" if gone else "unavailable", "abandoned" if gone else "changed",
                                        f"The attempt changed during the push: {pushed}.")
                values = (*astuple(key), x, x, self.clock())
                con.execute(f"INSERT INTO published_branch ({PUBLISHED}) VALUES ({marks(PUBLISHED)})", values)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotPublished("unavailable", "store", f"{type(error).__name__}: {pushed}; rerun to record it.")
        return BranchPublished(x, x)


def _policy(repo: Repo, branch: str, x: str) -> str:
    """Why `origin` refused a push that is not a stale tip: a ref name collision (a branch under `<branch>/`, or a branch
    named `task`, which Git cannot hold beside it) is named; else the remote's own policy."""
    try:
        clash = [ref.name for ref in repo.ls_remote(REMOTE, [f"refs/heads/{branch}/*", "refs/heads/task"])]
    except GitUnavailable:
        clash: list[str] = []
    if clash:
        return f"`{REMOTE}` holds {', '.join(clash)}, which cannot exist beside {branch} (a ref name collision): rename or delete it."
    return f"`{REMOTE}` refused the push by its own policy: push {x} by hand to see why."


def _rejected(repo: Repo, branch: str, x: str) -> NotPublished:
    """The remote's `task/<id>` moved: one `ls_remote` names its tip T, for the refusal word only. It reads the fetch side,
    which a `pushurl`/`pushInsteadOf` may make another repository than the push target, so nothing is recorded from it;
    a rerun whose push is `Pushed` (up to date) records. Nothing is pushed again or fetched."""
    try:
        advertised = repo.ls_remote(REMOTE, ["refs/heads/" + branch])
    except GitUnavailable:
        return _unavailable("remote", f"`{REMOTE}` refused the push and could not be read again: rerun.")
    t = next((ref.oid for ref in advertised if ref.name == "refs/heads/" + branch), None)
    if t is None or t == x:  # deleted meanwhile, or another publisher won the race: a rerun pushes and records
        return _unavailable("changed", f"`{REMOTE}`'s {branch} changed during the push: rerun.")
    try:
        relation = _relation(repo, x, t)
    except (MissingRevision, GitReadFailure):  # T is not in this repository
        return _refused("remote_moved", f"`{REMOTE}`'s {branch} is at {t}, unknown here: `git fetch {REMOTE} {branch}`, then rerun.")
    except GitUnavailable as error:
        return _unavailable("git", f"Git could not compare {x} with {t} ({type(error).__name__}): rerun.")
    words: dict[str, tuple[Literal["refused", "unavailable"], str, str]] = {
        "behind": ("unavailable", "changed", f"`{REMOTE}`'s {branch} is at {t}, behind {x}; it moved during the push: rerun."),
        "ahead": ("refused", "remote_ahead", f"`{REMOTE}`'s {branch} is at {t}, which already contains {x} and more: not "
                  "recorded; compare them, the factory never forces."),
        "diverged": ("refused", "diverged", f"`{REMOTE}`'s {branch} is at {t}, which does not contain {x}: compare {x}..{t}; "
                     "never forced."),
    }
    kind, reason, detail = words[relation]
    return NotPublished(kind, reason, f"{detail} {NOTHING}")


def _relation(repo: Repo, x: str, t: str) -> Literal["ahead", "behind", "diverged"]:
    """How the remote tip T stands to X, both known here: T contains X, X contains T, or neither."""
    if repo.is_ancestor(x, t):
        return "ahead"
    return "behind" if repo.is_ancestor(t, x) else "diverged"
