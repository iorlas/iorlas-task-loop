"""Admit one plan attempt: the only writer of `reservation` and of the admitted `plan_attempt` row; it runs nothing.

An admitted attempt stays unregistered (entry_* NULL): the body refuses it with `unregistered_entry` until a later
slice registers its entry. One attempt per task; nothing here releases, retries or replaces one.
"""

import math
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

from beads_client import BdError
from git_porcelain import GitUnavailable, Repo

from taskloop.plan_files import EvidenceError, PlanFiles
from taskloop.plan_schema import ATTEMPT_ADMITTED, RESERVATION, current, marks
from taskloop.plan_types import AttemptKey, FileRef
from taskloop.repo import RepoId, UnsupportedCheckout, inspect_repo
from taskloop.slots import SlotsUnavailable, SlotView, observe
from taskloop.task import TaskInspection, TaskInspectionError

type Claim = Callable[[str, str], bool]  # (tracker root, task id): True taken, False held elsewhere, BdError unknown
type Unclaim = Callable[[str, str], bool]  # fenced to this actor's own claim; False: not released
type Tasks = Callable[[str, str, str], TaskInspection]  # (task id, backlog, tracker root)
type Checkouts = Callable[[Path], Repo]
type Refusal = Literal[
    "choices", "deadline", "expired", "task", "checkout", "no_free_slot", "task_attempted", "input", "claimed_elsewhere", "constraint"
]
GENERATION = 1  # fixed until a release slice introduces monotonic generations
NOT_CLAIMED = frozenset({"missing_binary", "version", "not_found", "lint"})  # BdError kinds where the claim certainly did not happen


@dataclass(frozen=True)
class AdmitRequest:
    """Every choice is the caller's; nothing is discovered or defaulted. `deadline` is wall-clock seconds."""

    task_id: str
    backlog: str
    tracker_root: str
    checkout: Path
    model: str
    effort: str
    sandbox: str
    deadline: float


@dataclass(frozen=True)
class Admitted:
    key: AttemptKey
    slot: str


@dataclass(frozen=True)
class AdmitRefused:
    reason: Refusal
    slots: tuple[SlotView, ...] = ()
    claim_leaked: bool = False
    detail: str = ""


@dataclass(frozen=True)
class AdmitUnavailable:
    what: Literal["tracker", "git", "store"]
    claim_leaked: bool = False
    detail: str = ""


type AdmitResult = Admitted | AdmitRefused | AdmitUnavailable


@dataclass(frozen=True)
class _Prepared:
    request: AdmitRequest
    text: str
    repo: Repo
    repo_id: RepoId


def why(error: BaseException) -> str:
    """The failure's type and message, bounded for a result."""
    return f"{type(error).__name__}: {error}"[:300]


def task_text(task: TaskInspection) -> str:
    """The task's own prose, stored as the input; no prompt template."""
    return f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}\n"


class PlanAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        files: PlanFiles,
        tasks: Tasks,
        checkouts: Checkouts,
        claim: Claim,
        unclaim: Unclaim,
        clock: Callable[[], float],
    ) -> None:
        self.connect, self.begin, self.files, self.tasks, self.checkouts = connect, begin, files, tasks, checkouts
        self.claim, self.unclaim, self.clock = claim, unclaim, clock

    def admit(self, request: AdmitRequest) -> AdmitResult:
        prepared = self._prepare(request)
        if not isinstance(prepared, _Prepared):
            return prepared
        observed = self._observe(prepared)
        if not isinstance(observed, tuple):
            return observed
        con, free = observed
        key = AttemptKey(uuid4().hex, secrets.token_hex(16), GENERATION)
        try:
            ref = self.files.put_input(key, prepared.text)
        except (EvidenceError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))
        return self._claimed(con, prepared, free, key, ref)

    def _prepare(self, request: AdmitRequest) -> _Prepared | AdmitRefused | AdmitUnavailable:
        """Read-only checks; any failure refuses before a file, claim or row exists."""
        refused = self._choices(request)
        if refused is not None:
            return refused
        task = self._task(request)
        if not isinstance(task, TaskInspection):
            return task
        try:
            checkout = request.checkout.expanduser().resolve()
            repo = self.checkouts(checkout)
            inspection = inspect_repo(repo, checkout)
        except (UnsupportedCheckout, RuntimeError, OSError) as error:
            return AdmitRefused("checkout", detail=why(error))
        except GitUnavailable as error:
            return AdmitUnavailable("git", detail=why(error))
        return _Prepared(request, task_text(task), repo, inspection.repo_id)

    def _choices(self, request: AdmitRequest) -> AdmitRefused | None:
        if not all(value.strip() for value in (request.model, request.effort, request.sandbox)):
            return AdmitRefused("choices")
        if not math.isfinite(request.deadline):
            return AdmitRefused("deadline")
        return AdmitRefused("expired") if self.clock() >= request.deadline else None

    def _task(self, request: AdmitRequest) -> TaskInspection | AdmitRefused | AdmitUnavailable:
        try:
            return self.tasks(request.task_id, request.backlog, request.tracker_root)
        except TaskInspectionError as error:
            if error.kind == "tracker_unavailable":
                return AdmitUnavailable("tracker", detail=why(error))
            return AdmitRefused("task", detail=f"{error.kind}: {why(error)}")

    def _open(self) -> sqlite3.Connection:
        con = self.connect()
        if con is None or not current(con):
            raise sqlite3.DatabaseError("Factory database unavailable or incompatible")
        return con

    def _observe(self, prepared: _Prepared) -> tuple[sqlite3.Connection, tuple[str, ...]] | AdmitRefused | AdmitUnavailable:
        """An attempted task, then no free slot, refuse before any effect; store failure never counts as free."""
        try:
            con = self._open()
            if _attempted(con, prepared.request):
                return AdmitRefused("task_attempted")
            views = observe(con, prepared.repo, prepared.repo_id)
        except (sqlite3.Error, SlotsUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        if any(view.reason == "store_unavailable" for view in views):
            return AdmitUnavailable("store", detail="Reservations unreadable")
        free = tuple(view.name for view in views if view.state == "free")
        return (con, free) if free else AdmitRefused("no_free_slot", views)

    def _claimed(self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[str, ...], key: AttemptKey, ref: FileRef) -> AdmitResult:
        """Claim outside any transaction, then commit; a pre-commit failure after a claim is compensated by `_compensate`."""
        request = prepared.request
        try:
            taken = self.claim(request.tracker_root, request.task_id)
        except BdError as error:
            leaked = False if error.kind in NOT_CLAIMED else self._compensate(request)  # otherwise the outcome is unknown
            return AdmitUnavailable("tracker", leaked, why(error))
        if not taken:
            return AdmitRefused("claimed_elsewhere")
        try:
            outcome = self._commit(con, prepared, free, key, ref)
        except sqlite3.IntegrityError as error:  # caught after the rollback; every constraint is pre-checked, so it means a schema mismatch
            outcome = AdmitRefused("constraint", detail=why(error))
        except sqlite3.Error as error:
            outcome = AdmitUnavailable("store", detail=why(error))
        except BaseException:
            self._compensate(request)
            raise
        if isinstance(outcome, Admitted):
            return outcome
        return replace(outcome, claim_leaked=self._compensate(request))

    def _compensate(self, request: AdmitRequest) -> bool:
        """Release the claim only when a fresh read shows no attempt for the task; True when the claim may have leaked.

        `Bd.claim` is idempotent for this actor, so a claim that an attempt already holds is never ours to release; when that
        read fails the claim is kept and reported as leaked. The release is fenced to this actor, never forced or retried.
        """
        try:
            if _attempted(self._open(), request):
                return False
        except sqlite3.Error:
            return True
        try:
            return not self.unclaim(request.tracker_root, request.task_id)
        except BdError:
            return True

    def _commit(
        self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[str, ...], key: AttemptKey, ref: FileRef
    ) -> Admitted | AdmitRefused:
        """Under the write lock the reads are authoritative: the task first, then the observed-free slots, then both rows."""
        request, repo_id = prepared.request, prepared.repo_id
        with self.begin(con):
            if _attempted(con, request):
                return AdmitRefused("task_attempted")
            chosen = next((slot for name in free if (slot := _unheld(con, repo_id, name)) is not None), None)
            if chosen is None:
                return AdmitRefused("no_free_slot")
            name, cwd = chosen
            held = {"slot": name, "repo_id": repo_id, "cwd": cwd, "generation": GENERATION, "attempt_id": key.attempt_id}
            con.execute(f"INSERT INTO reservation ({RESERVATION}) VALUES ({marks(RESERVATION)})", bound(RESERVATION, held))
            attempt = {
                "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
                "adapter": "beads", "backlog": request.backlog, "task_id": request.task_id, "repo_id": repo_id, "slot": name,
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": request.model,
                "effort": request.effort, "sandbox": request.sandbox, "deadline": request.deadline,
            }
            values = bound(ATTEMPT_ADMITTED, attempt)
            con.execute(f"INSERT INTO plan_attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", values)
        return Admitted(key, name)


def bound(columns: str, values: Mapping[str, object]) -> tuple[object, ...]:
    """Values in the order of the owning column list, by name; a missing or extra column is a programming error."""
    names = columns.split(",")
    if set(names) != set(values):
        raise ValueError(f"Columns {sorted(set(names) ^ set(values))} do not match {columns}")
    return tuple(values[name] for name in names)


def _unheld(con: sqlite3.Connection, repo_id: RepoId, name: str) -> tuple[str, str] | None:
    row: tuple[object, ...] | None = con.execute(
        "SELECT name,cwd FROM slot s WHERE repo_id=? AND name=? AND NOT EXISTS "
        "(SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)",
        (repo_id, name),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[0], str) or not isinstance(row[1], str):
        raise sqlite3.DatabaseError("Malformed slot row")
    return row[0], row[1]


def _attempted(con: sqlite3.Connection, request: AdmitRequest) -> bool:
    found = con.execute(
        "SELECT 1 FROM plan_attempt WHERE adapter='beads' AND backlog=? AND task_id=?", (request.backlog, request.task_id)
    ).fetchone()
    return found is not None
