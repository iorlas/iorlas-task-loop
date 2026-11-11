"""Admit an attempt: the only writer of the admitted `attempt` row and of a new `reservation` row; it runs nothing.

A task's first attempt takes a free slot and the tracker claim (`admit`), after the task branch rule passed for that
slot's HEAD (`prepare.branch_refusal`, read-only, before anything is written or claimed); a repeat is admitted by
`admit_chain`, through the shared pieces here (the deadline check, the store, the attempt row and the slot's counter).
An admitted attempt stays unregistered (entry_* NULL): the body refuses it with
`unregistered_entry` until `AttemptStore.register_entry` registers its entry. The tracker root, resolved, is stored with the
attempt (a repeat copies it): the entry renews the claim there, an abandon returns it there. The slot's HEAD the attempt
starts from (D) is stored as `slot_head` (a repeat copies it): a release parks the slot back there.

Each slot's `generation` is the last reservation generation issued for it, so a generation is never reused after a
release: a fresh admission takes one above every observed-free slot's counter, a repeat the next one. `seq` orders a
task's attempts (a repeat or a fresh attempt after an abandon takes the next); `number` is the attempt's place in its
step. A task whose current attempt was abandoned (`slot_release`) is admitted again as a fresh attempt 1. Nothing here
releases a slot; the claim is returned only to compensate a failed admission.
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

from taskloop.attempt_types import AttemptKey, Checkouts, FileRef
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.factory_schema import ATTEMPT_ADMITTED, RESERVATION, current, marks
from taskloop.prepare import DIVERGED, branch_refusal
from taskloop.repo import RepoId, UnsupportedCheckout, inspect_repo
from taskloop.slots import Probe, SlotsUnavailable, SlotView, observe
from taskloop.steps import STEPS, kind
from taskloop.task import TaskInspection, TaskInspectionError

type Claim = Callable[[str, str], bool]  # (tracker root, task id): True taken, False held elsewhere, BdError unknown
type Unclaim = Callable[[str, str], bool]  # fenced to this actor's own claim; False: not released
type Tasks = Callable[[str, str, str], TaskInspection]  # (task id, backlog, tracker root)
type Refusal = Literal[
    "choices", "deadline", "expired", "task", "checkout", "no_free_slot", "task_attempted", "input", "claimed_elsewhere", "constraint",
    "not_repeatable", "repeat_cap", "branch_name", "branch_held", "branch_diverged",
]
FIRST = STEPS[0].step  # a fresh admission's step: the first one
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
class Free:
    """An observed-free slot whose HEAD (D) passed the branch rule."""

    name: str
    head: str


@dataclass(frozen=True)
class _Prepared:
    request: AdmitRequest
    text: str
    repo: Repo
    repo_id: RepoId


def why(error: BaseException) -> str:
    """The failure's type and message, bounded for a result."""
    return f"{type(error).__name__}: {error}"[:300]


def task_text(task: TaskInspection, step: str) -> str:
    """The step kind's input for the task (its own prose, then the step's closing words), stored as the admitted input
    under its digest."""
    found = kind(step)
    return found.input_text(task, found.rules(task.reference.task_id))


class AttemptAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        files: EvidenceFiles,
        tasks: Tasks,
        checkouts: Checkouts,
        claim: Claim,
        unclaim: Unclaim,
        clock: Callable[[], float],
        probe: Probe,
    ) -> None:
        """`probe` reads a free-looking slot's lock (`slot_lock.probe`): a slot a release is still parking is not free."""
        self.connect, self.begin, self.files, self.tasks, self.checkouts = connect, begin, files, tasks, checkouts
        self.claim, self.unclaim, self.clock, self.probe = claim, unclaim, clock, probe

    def admit(self, request: AdmitRequest) -> AdmitResult:
        prepared = self._prepare(request)
        if not isinstance(prepared, _Prepared):
            return prepared
        observed = self._observe(prepared)
        if not isinstance(observed, tuple):
            return observed
        con, views = observed
        free = branched(prepared.repo, prepared.request.task_id, views)
        if not isinstance(free, tuple):
            return free
        try:
            generation = issued(con, prepared.repo_id, tuple(each.name for each in free)) + 1
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))
        key = AttemptKey(uuid4().hex, secrets.token_hex(16), generation)  # the key names the evidence directory
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
        return _Prepared(replace(request, tracker_root=str(tracker)), task_text(task, FIRST), repo, inspection.repo_id)

    def _choices(self, request: AdmitRequest) -> AdmitRefused | None:
        if not all(value.strip() for value in (request.model, request.effort, request.sandbox)):
            return AdmitRefused("choices")
        return deadline_refusal(self.clock, request.deadline)

    def _task(self, request: AdmitRequest) -> TaskInspection | AdmitRefused | AdmitUnavailable:
        try:
            return self.tasks(request.task_id, request.backlog, request.tracker_root)
        except TaskInspectionError as error:
            if error.kind == "tracker_unavailable":
                return AdmitUnavailable("tracker", detail=why(error))
            return AdmitRefused("task", detail=f"{error.kind}: {why(error)}")

    def _observe(self, prepared: _Prepared) -> tuple[sqlite3.Connection, tuple[SlotView, ...]] | AdmitRefused | AdmitUnavailable:
        """An attempted task, then no free slot, refuse before any effect; store failure never counts as free."""
        try:
            con = open_store(self.connect)
            if _attempted(con, prepared.request):
                return AdmitRefused("task_attempted")
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))
        free = free_slots(con, prepared.repo, prepared.repo_id, self.probe)
        return (con, free) if isinstance(free, tuple) else free

    def _claimed(self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[Free, ...], key: AttemptKey, ref: FileRef) -> AdmitResult:
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
            result = self._commit(con, prepared, free, key, ref)
        except sqlite3.IntegrityError as error:  # caught after the rollback; every constraint is pre-checked, so it means a schema mismatch
            result = AdmitRefused("constraint", detail=why(error))
        except sqlite3.Error as error:
            result = AdmitUnavailable("store", detail=why(error))
        except BaseException:
            self._compensate(request)
            raise
        if isinstance(result, Admitted):
            return result
        return replace(result, claim_leaked=self._compensate(request))

    def _compensate(self, request: AdmitRequest) -> bool:
        """Release the claim only when a fresh read shows no attempt for the task; True when the claim may have leaked.

        `Bd.claim` is idempotent for this actor, so a claim that an attempt already holds is never ours to release; when that
        read fails the claim is kept and reported as leaked. The release is fenced to this actor, never forced or retried.
        """
        try:
            if _attempted(open_store(self.connect), request):
                return False
        except sqlite3.Error:
            return True
        try:
            return not self.unclaim(request.tracker_root, request.task_id)
        except BdError:
            return True

    def _commit(
        self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[Free, ...], key: AttemptKey, ref: FileRef
    ) -> Admitted | AdmitRefused:
        """Under the write lock the reads are authoritative: the task first, then the observed-free slots (the lowest one
        still unheld whose counter is below the key's generation), then both rows and the slot's counter."""
        request, repo_id, generation = prepared.request, prepared.repo_id, key.reservation_generation
        with self.begin(con):
            if _attempted(con, request):
                return AdmitRefused("task_attempted")
            chosen = next((slot for each in free if (slot := unheld(con, repo_id, each, generation)) is not None), None)
            if chosen is None:
                return AdmitRefused("no_free_slot")
            name, head = chosen
            held = {"slot": name, "repo_id": repo_id, "generation": generation, "attempt_id": key.attempt_id}
            con.execute(f"INSERT INTO reservation ({RESERVATION}) VALUES ({marks(RESERVATION)})", bound(RESERVATION, held))
            issue(con, repo_id, name, generation)
            insert_attempt(con, {
                "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
                "adapter": "beads", "backlog": request.backlog, "task_id": request.task_id, "tracker_root": request.tracker_root,
                "repo_id": repo_id, "slot": name, "step": FIRST,
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": request.model,
                "effort": request.effort, "sandbox": request.sandbox, "deadline": request.deadline, "number": 1,
                "previous_attempt_id": None, "repeat_reason": None, "seq": _next_seq(con, request), "slot_head": head,
            })
        return Admitted(key, name)


def deadline_refusal(clock: Callable[[], float], deadline: float) -> AdmitRefused | None:
    if not math.isfinite(deadline):
        return AdmitRefused("deadline")
    return AdmitRefused("expired") if clock() >= deadline else None


def open_store(connect: Callable[[], sqlite3.Connection | None]) -> sqlite3.Connection:
    con = connect()
    if con is None or not current(con):
        raise sqlite3.DatabaseError("Factory database unavailable or incompatible")
    return con


def free_slots(
    con: sqlite3.Connection, repo: Repo, repo_id: RepoId, probe: Probe
) -> tuple[SlotView, ...] | AdmitRefused | AdmitUnavailable:
    """The observed-free slots, read-only; a store failure never counts as free."""
    try:
        views = observe(con, repo, repo_id, probe)
    except (sqlite3.Error, SlotsUnavailable) as error:
        return AdmitUnavailable("store", detail=why(error))
    if any(view.reason == "store_unavailable" for view in views):
        return AdmitUnavailable("store", detail="Reservations unreadable")
    free = tuple(view for view in views if view.state == "free")
    return free or AdmitRefused("no_free_slot", views)


def branched(repo: Repo, task_id: str, free: tuple[SlotView, ...]) -> tuple[Free, ...] | AdmitRefused | AdmitUnavailable:
    """The task branch rule, read-only, before any file, claim or row: the free slots whose HEAD (D) it passes. The
    entry checks it again before it creates the branch (`prepare`)."""
    try:
        heads = {info.path: info.head for info in repo.worktrees()}
        found = branch_refusal(repo, task_id, tuple(head for view in free if (head := heads.get(view.path)) is not None))
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))
    if isinstance(found, str):
        return AdmitRefused(found, detail=DIVERGED.format(task=task_id) if found == "branch_diverged" else "")
    passing = tuple(Free(view.name, head) for view in free if (head := heads.get(view.path)) is not None and head in found.passing)
    return passing or AdmitRefused("no_free_slot")


def insert_attempt(con: sqlite3.Connection, attempt: Mapping[str, object]) -> None:
    """The admitted attempt row, inside the caller's write transaction."""
    con.execute(f"INSERT INTO attempt ({ATTEMPT_ADMITTED}) VALUES ({marks(ATTEMPT_ADMITTED)})", bound(ATTEMPT_ADMITTED, attempt))


def issue(con: sqlite3.Connection, repo_id: object, slot: object, generation: int) -> None:
    """The slot's counter: the last reservation generation issued for it."""
    con.execute("UPDATE slot SET generation=? WHERE repo_id=? AND name=?", (generation, repo_id, slot))


def bound(columns: str, values: Mapping[str, object]) -> tuple[object, ...]:
    """Values in the order of the owning column list, by name; a missing or extra column is a programming error."""
    names = columns.split(",")
    if set(names) != set(values):
        raise ValueError(f"Columns {sorted(set(names) ^ set(values))} do not match {columns}")
    return tuple(values[name] for name in names)


def as_count(value: object) -> int:
    if isinstance(value, int):
        return value
    raise sqlite3.DatabaseError("Malformed stored integer")


def unheld(con: sqlite3.Connection, repo_id: RepoId, free: Free, generation: int) -> tuple[str, str] | None:
    """The slot's name with its D, when it is unreserved and its counter is below `generation`."""
    row: tuple[object, ...] | None = con.execute(
        "SELECT name FROM slot s WHERE repo_id=? AND name=? AND generation<? AND NOT EXISTS "
        "(SELECT 1 FROM reservation r WHERE r.repo_id=s.repo_id AND r.slot=s.name)",
        (repo_id, free.name, generation),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[0], str):
        raise sqlite3.DatabaseError("Malformed slot row")
    return row[0], free.head


def issued(con: sqlite3.Connection, repo_id: RepoId, names: tuple[str, ...]) -> int:
    """The highest generation issued for any of the named slots (0 when none was)."""
    marked = ",".join("?" * len(names))
    found = f"SELECT coalesce(max(generation),0) FROM slot WHERE repo_id=? AND name IN ({marked})"
    row = con.execute(found, (repo_id, *names)).fetchone()
    return as_count(None if row is None else row[0])


def _next_seq(con: sqlite3.Connection, request: AdmitRequest) -> int:
    row = con.execute(
        "SELECT coalesce(max(seq),0)+1 FROM attempt WHERE adapter='beads' AND backlog=? AND task_id=?",
        (request.backlog, request.task_id),
    ).fetchone()
    return as_count(None if row is None else row[0])


def _attempted(con: sqlite3.Connection, request: AdmitRequest) -> bool:
    """The task's current attempt (its highest `seq`) exists and its abandon is not finished: only an abandoned attempt
    whose claim was returned (`unclaimed`, or found `not_held`) starts the task again. While the claim is `unclaiming`,
    a fresh claim could be undone by the abandon's own unclaim, so the task still counts as attempted."""
    found = con.execute(
        """SELECT EXISTS (SELECT 1 FROM slot_release r WHERE r.attempt_id=p.attempt_id
        AND r.claim IN ('unclaimed','not_held')) FROM attempt p
        WHERE p.adapter='beads' AND p.backlog=? AND p.task_id=? ORDER BY p.seq DESC LIMIT 1""",
        (request.backlog, request.task_id),
    ).fetchone()
    return found is not None and not found[0]
