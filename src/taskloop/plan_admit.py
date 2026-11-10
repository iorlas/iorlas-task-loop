"""Admit a plan attempt: the only writer of `reservation` and of the admitted `plan_attempt` row; it runs nothing.

A task's first attempt takes a free slot and the tracker claim (`admit`), after the task branch rule passed for that
slot's HEAD (`plan_prepare.branch_refusal`, read-only, before anything is written or claimed); a repeat (`admit_repeat`) is the step's next
attempt, which takes over the reservation its previous attempt holds in the same transaction, so the slot is never
released between attempts. An admitted attempt stays unregistered (entry_* NULL): the body refuses it with
`unregistered_entry` until `PlanStore.register_entry` registers its entry. The tracker root, resolved, is stored with the
attempt (a repeat copies it): the entry renews the claim there. Nothing here releases a slot or a claim.
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
from taskloop.plan_prepare import DIVERGED, branch_refusal
from taskloop.plan_schema import ATTEMPT_ADMITTED, RESERVATION, current, marks
from taskloop.plan_types import ATTEMPTS, PLAN_NAME, AttemptKey, Checkouts, FileRef, RepeatReason, plan_stage
from taskloop.repo import RepoId, UnsupportedCheckout, inspect_repo
from taskloop.slots import SlotsUnavailable, SlotView, observe
from taskloop.task import TaskInspection, TaskInspectionError

type Claim = Callable[[str, str], bool]  # (tracker root, task id): True taken, False held elsewhere, BdError unknown
type Unclaim = Callable[[str, str], bool]  # fenced to this actor's own claim; False: not released
type Tasks = Callable[[str, str, str], TaskInspection]  # (task id, backlog, tracker root)
type Refusal = Literal[
    "choices", "deadline", "expired", "task", "checkout", "no_free_slot", "task_attempted", "input", "claimed_elsewhere", "constraint",
    "not_repeatable", "repeat_cap", "branch_name", "branch_held", "branch_diverged",
]
GENERATION = 1  # a fresh admission's; a repeat advances it on the held reservation (until a release slice moves it to `slot`)
# The previous attempt under the write lock: its numbers, its copied choices, a successor, the held reservation, a valid
# clean completely published `planned`/`unchanged` answer (the gate of `plan_commit` and the verdict), no verdict, and
# the tracker root its claim was taken at (copied: a repeat claims nothing).
PREVIOUS = """SELECT p.generation,p.number,p.adapter,p.backlog,p.task_id,p.repo_id,p.slot,p.model,p.effort,p.sandbox,
EXISTS (SELECT 1 FROM plan_attempt s WHERE s.previous_attempt_id=p.attempt_id),
p.phase='captured' AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND EXISTS (SELECT 1 FROM plan_execution e WHERE e.attempt_id=p.attempt_id AND e.answer_kind='valid' AND e.rc=0 AND e.timed_out=0
 AND e.disposition IN ('planned','unchanged') AND e.publication='complete')
AND NOT EXISTS (SELECT 1 FROM plan_verification v WHERE v.attempt_id=p.attempt_id),
p.tracker_root
FROM plan_attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""
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
class RepeatRequest:
    """The step's next attempt: `previous` is the current attempt it repeats, `text` its complete admitted input."""

    previous: AttemptKey
    text: str
    deadline: float
    reason: RepeatReason


class _Lost(Exception):
    """No reservation row moved from the previous attempt: roll the new attempt back."""


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
    """The task's own prose, then the fixed closing words of the plan stage (where the plan goes, `unchanged` or `planned`,
    no Git write: the factory commits the listed paths), stored as the admitted input under its digest."""
    root = plan_stage(task.reference.task_id).root
    closing = (
        f"First read `{root}{PLAN_NAME}` if it exists. If it is still valid for the task and the code as they are now, change "
        f"nothing and answer `unchanged`. Otherwise write the plan there (rewrite it in place if it exists) and answer "
        f"`planned`; other files only under `{root}`. You may read Git; do not run `git add`, `git commit`, `git push` or "
        "any other Git write; they will fail. With `planned`, list in `paths` every file you want committed and give a "
        "one-line commit `message`; the factory commits exactly those paths. Remove any other file you created. Anything "
        "left uncommitted is reported back to you as a failed stage."
    )
    return f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}\n\n{closing}\n"


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
        con, views = observed
        free = self._branched(prepared, views)
        if not isinstance(free, tuple):
            return free
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
            tracker = Path(request.tracker_root).expanduser().resolve()
        except (RuntimeError, OSError) as error:
            return AdmitRefused("task", detail=why(error))
        try:
            checkout = request.checkout.expanduser().resolve()
            repo = self.checkouts(checkout)
            inspection = inspect_repo(repo, checkout)
        except (UnsupportedCheckout, RuntimeError, OSError) as error:
            return AdmitRefused("checkout", detail=why(error))
        except GitUnavailable as error:
            return AdmitUnavailable("git", detail=why(error))
        # the root as resolved now is the one claimed, stored and renewed (.4.3.1.9)
        return _Prepared(replace(request, tracker_root=str(tracker)), task_text(task), repo, inspection.repo_id)

    def _choices(self, request: AdmitRequest) -> AdmitRefused | None:
        if not all(value.strip() for value in (request.model, request.effort, request.sandbox)):
            return AdmitRefused("choices")
        return self._deadline(request.deadline)

    def _deadline(self, deadline: float) -> AdmitRefused | None:
        if not math.isfinite(deadline):
            return AdmitRefused("deadline")
        return AdmitRefused("expired") if self.clock() >= deadline else None

    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        """The next attempt N of `previous` (P), its input written first under N's key: in one write transaction, every
        check re-read under the lock, insert N (P's choices, number + 1, generation + 1) and move the held reservation
        from P to N, fenced on P and its generation. Afterwards every fenced write of P is refused."""
        refused = self._deadline(request.deadline)
        if refused is not None:
            return refused
        previous = request.previous
        key = AttemptKey(uuid4().hex, secrets.token_hex(16), previous.reservation_generation + 1)
        try:
            ref = self.files.put_input(key, request.text)
        except (EvidenceError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))
        try:
            return self._takeover(self._open(), request, key, ref)
        except _Lost:
            return AdmitRefused("task_attempted")
        except sqlite3.IntegrityError as error:  # caught after the rollback: a concurrent repeat's UNIQUE number or previous
            return AdmitRefused("task_attempted", detail=why(error))
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))

    def _takeover(self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef) -> Admitted | AdmitRefused:
        previous = request.previous
        with self.begin(con):
            row: tuple[object, ...] | None = con.execute(PREVIOUS, (previous.attempt_id, previous.dispatch_token,
                                                                    previous.reservation_generation)).fetchone()
            if row is None:
                return AdmitRefused("not_repeatable")
            if row[10]:
                return AdmitRefused("task_attempted")
            number = row[1]
            if not isinstance(number, int) or number >= ATTEMPTS:
                return AdmitRefused("repeat_cap")
            if not row[11]:
                return AdmitRefused("not_repeatable")
            refused = self._deadline(request.deadline)
            if refused is not None:
                return refused
            attempt = {
                "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
                "adapter": row[2], "backlog": row[3], "task_id": row[4], "tracker_root": row[12], "repo_id": row[5], "slot": row[6],
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": row[7], "effort": row[8],
                "sandbox": row[9], "deadline": request.deadline, "number": number + 1, "previous_attempt_id": previous.attempt_id,
                "repeat_reason": request.reason,
            }
            values = bound(ATTEMPT_ADMITTED, attempt)
            con.execute(f"INSERT INTO plan_attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", values)
            moved = con.execute(
                """UPDATE reservation SET attempt_id=?,generation=generation+1 WHERE repo_id=? AND slot=? AND attempt_id=?
                AND generation=?""",
                (key.attempt_id, row[5], row[6], previous.attempt_id, previous.reservation_generation),
            )
            if moved.rowcount != 1:
                raise _Lost
        return Admitted(key, str(row[6]))

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

    def _observe(self, prepared: _Prepared) -> tuple[sqlite3.Connection, tuple[SlotView, ...]] | AdmitRefused | AdmitUnavailable:
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
        free = tuple(view for view in views if view.state == "free")
        return (con, free) if free else AdmitRefused("no_free_slot", views)

    def _branched(self, prepared: _Prepared, free: tuple[SlotView, ...]) -> tuple[str, ...] | AdmitRefused | AdmitUnavailable:
        """The task branch rule, read-only, before any file, claim or row: the free slots whose HEAD (D) it passes. The
        entry checks it again before it creates the branch (`plan_prepare`)."""
        task_id = prepared.request.task_id
        try:
            heads = {info.path: info.head for info in prepared.repo.worktrees()}
            found = branch_refusal(prepared.repo, task_id, tuple(head for view in free if (head := heads.get(view.path)) is not None))
        except GitUnavailable as error:
            return AdmitUnavailable("git", detail=why(error))
        if isinstance(found, str):
            return AdmitRefused(found, detail=DIVERGED.format(task=task_id) if found == "branch_diverged" else "")
        names = tuple(view.name for view in free if heads.get(view.path) in found.passing)
        return names or AdmitRefused("no_free_slot")

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
                "adapter": "beads", "backlog": request.backlog, "task_id": request.task_id, "tracker_root": request.tracker_root,
                "repo_id": repo_id, "slot": name,
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": request.model,
                "effort": request.effort, "sandbox": request.sandbox, "deadline": request.deadline, "number": 1,
                "previous_attempt_id": None, "repeat_reason": None,
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
