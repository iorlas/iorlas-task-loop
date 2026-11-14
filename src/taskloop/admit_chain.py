"""Continue a claimed task, copying its tracker root without claiming again.
A repeat atomically takes over the held reservation, retaining its original park point.
An advance follows a verified, released and published step into a free slot, requiring its previous result
in the task branch. Both store earlier-answer context before their short, fenced admission transaction.
"""

import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import astuple, dataclass, replace
from functools import partial
from pathlib import Path

from git_porcelain import GitUnavailable, Repo

from taskloop.admit import (
    AdmitRefused,
    Admitted,
    AdmitUnavailable,
    Free,
    Tasks,
    branched,
    checkout_repo,
    deadline_refusal,
    free_slots,
    issued,
    open_store,
    read_task,
    task_text,
    unheld,
    why,
)
from taskloop.admit_rows import as_count, insert_attempt, issue, reserve
from taskloop.agents.settings import AgentSetting, encode_policy
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import ATTEMPTS, AttemptKey, Checkouts, FileRef, RepeatReason, SlotFiles
from taskloop.discussion import CollectDiscussion, empty
from taskloop.drain.models import BLOCKED, Reason
from taskloop.drain.store import blocked
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.earlier_input import EarlierInput, commit_names
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.factory_schema import LATER, REPEATED
from taskloop.git_views import GitProfileFiles
from taskloop.hold_store import HoldStore
from taskloop.ids import Ids
from taskloop.input_context import InputError
from taskloop.input_context import read as read_context
from taskloop.prepare import HEADS, ORIGIN_MAIN, REMOTES, lacks
from taskloop.repo import RepoId
from taskloop.slots import Probe, SlotGit
from taskloop.steps import is_agent, next_step
from taskloop.task import TaskInspection
from taskloop.tracker import ACTOR

# The previous attempt under the write lock: its numbers, its copied choices, a successor, the held reservation, a valid
# clean answer with its session complete, of effect `commit`/`keep` (the rule check of `factory_commit` and the verdict), no verdict, the
# tracker root its claim was taken at (copied: a repeat claims nothing), its task-wide order, D, step and label (all carried on).
PREVIOUS = f"""SELECT p.generation,p.number,p.adapter,p.backlog,p.task_id,p.repo_id,p.slot,p.model,p.effort,p.access_policy,
{REPEATED},
p.phase='captured' AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id AND e.answer_kind='valid' AND e.rc=0 AND e.timed_out=0
 AND e.effect IN ('commit','keep') AND e.session_state='complete')
AND NOT EXISTS (SELECT 1 FROM verification v WHERE v.attempt_id=p.attempt_id),
p.tracker_root,p.seq,p.slot_head,p.step,p.label,p.harness,p.provider
FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""


@dataclass(frozen=True)
class RepeatRequest:
    """The step's next attempt: `previous` is the current attempt it repeats, `text` its complete admitted input."""

    previous: AttemptKey
    text: str
    deadline: float
    reason: RepeatReason
    listing: tuple[str, ...] = ()  # what the failed verification listed; stored with the repeat, the verification's typed result


class _Lost(Exception):
    """No reservation row moved from the previous attempt: roll the new attempt back."""


class ChainAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        files: EvidenceFiles,
        clock: Callable[[], float],
        checkouts: Checkouts,
        slot_files: SlotFiles,
        *, ids: Ids,
    ) -> None:
        self.ids = ids
        self.connect, self.begin, self.files, self.clock = connect, begin, files, clock
        self.checkouts, self.slot_files = checkouts, slot_files

    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        """The next attempt N of `previous` (P), its input written first under N's key: in one write transaction, every
        check re-read under the lock, insert N (P's choices, number + 1, generation + 1) and move the held reservation
        from P to N, fenced on P and its generation. Afterwards every fenced write of P is refused."""
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        previous = request.previous
        key = AttemptKey(self.ids.hex(), self.ids.token(16), previous.reservation_generation + 1)
        try:
            reader = AttemptStore(self.connect, self.begin)
            earlier = reader.earlier_for(previous)
            if earlier is not None and earlier.key != previous:
                return AdmitRefused("task_attempted")
            text = request.text if earlier is None else EarlierInput(
                reader, self.files, HoldStore(self.connect, self.begin)).attach_slot(request.text, earlier, self.checkouts, self.slot_files)
            ref = self.files.put_input(key, text)
            return self._takeover(open_store(self.connect), request, key, ref, earlier)
        except (_Lost, sqlite3.IntegrityError) as error:
            return AdmitRefused("task_attempted", detail=why(error))
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        except (EvidenceError, InputError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))

    def _takeover(self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef,
                  earlier: EarlierAttempt | None) -> Admitted | AdmitRefused:
        with self.begin(con):
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            if AttemptStore(lambda: con).earlier_for(request.previous) != earlier:
                return AdmitRefused("task_attempted", detail="The earlier attempt changed while the input was being prepared.")
            return self._takeover_open(con, request, key, ref)

    def _takeover_open(self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef) -> Admitted | AdmitRefused:
        previous = request.previous
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
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        insert_attempt(con, {
            "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
            "adapter": row[2], "backlog": row[3], "task_id": row[4], "tracker_root": row[12], "repo_id": row[5], "slot": row[6],
            "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1, "model": row[7], "effort": row[8],
            "access_policy": row[9], "deadline": request.deadline, "number": number + 1, "previous_attempt_id": previous.attempt_id,
            "repeat_reason": request.reason, "repeat_listing": json.dumps(request.listing), "seq": as_count(row[13]) + 1,
            "slot_head": row[14], "step": row[15],
            "harness": row[17], "provider": row[18],
            "after_commit": None, "label": row[16],  # a repeat starts at E, the chain's own
        })
        moved = con.execute(
            """UPDATE reservation SET attempt_id=?,generation=generation+1 WHERE repo_id=? AND slot=? AND attempt_id=?
            AND generation=?""",
            (key.attempt_id, row[5], row[6], previous.attempt_id, previous.reservation_generation),
        )
        if moved.rowcount != 1:
            raise _Lost
        issue(con, row[5], row[6], key.reservation_generation)
        return Admitted(key, str(row[6]))


# The task's current attempt (its highest `seq`) under the write lock: its key, whether it is done (verified, released
# settled with the claim kept, its X published), its step, X, tracker root, order and label (the next step's copy).
CURRENT = """SELECT p.attempt_id,p.dispatch_token,p.generation,
EXISTS (SELECT 1 FROM verification v WHERE v.attempt_id=p.attempt_id AND v.verdict='verified')
AND EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id AND x.claim='kept')
AND EXISTS (SELECT 1 FROM published_branch b WHERE b.attempt_id=p.attempt_id AND b.commit_sha=p.end_commit),
p.step,p.end_commit,p.tracker_root,p.seq,p.label
FROM attempt p WHERE p.adapter='beads' AND p.backlog=? AND p.task_id=? ORDER BY p.seq DESC LIMIT 1"""


@dataclass(frozen=True)
class NextStepRequest:
    """Attempt 1 of the step after `previous`'s; every choice is the caller's (no label: claimed work is not ingested)."""

    previous: AttemptKey
    checkout: Path
    setting: AgentSetting
    deadline: float


@dataclass(frozen=True)
class Task:
    """The previous attempt's task, read before any effect; `current`: it is still the task's current attempt (also the
    checks admission's read, `check_admit`)."""

    backlog: str
    task_id: str
    tracker_root: str
    repo_id: str
    step: str
    current: bool
    end_commit: str | None  # X: the commit the next step starts from


@dataclass(frozen=True)
class _Ready:
    """Everything an advance read before any effect."""

    con: sqlite3.Connection
    found: Task
    step: str
    task: TaskInspection
    free: tuple[Free, ...]
    earlier: EarlierAttempt | None = None


class NextAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        files: EvidenceFiles,
        tasks: Tasks,
        checkouts: Checkouts,
        clock: Callable[[], float],
        probe: Probe,
        slot_files: SlotFiles,
        *, ids: Ids, discussion: CollectDiscussion = empty,
    ) -> None:
        """The ports of a fresh admission (`admit.AttemptAdmission`) without the claim: an advance never claims."""
        self.ids = ids
        self.discussion = discussion
        self.connect, self.begin, self.files, self.tasks, self.checkouts = connect, begin, files, tasks, checkouts
        self.clock, self.probe, self.slot_files = clock, probe, slot_files

    def admit_next(self, request: NextStepRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        """Read-only checks first (`_ready`); then the input under the new key; then one write transaction that re-reads
        every fact (`_advance`). No claim, so nothing to compensate."""
        ready = self._ready(request)
        if not isinstance(ready, _Ready):
            return ready
        found, names = ready.found, tuple(each.name for each in ready.free)
        try:
            key = AttemptKey(self.ids.hex(), self.ids.token(16), issued(ready.con, RepoId(found.repo_id), names) + 1)
            context = read_context(GitProfileFiles(request.checkout, self.checkouts), ready.free[0].source)
            discussion = self.discussion(ready.task, found.tracker_root)
            reader = AttemptStore(self.connect, self.begin)
            earlier = reader.earlier_for(request.previous)
            ready = replace(ready, earlier=earlier)
            text = EarlierInput(reader, self.files, HoldStore(self.connect, self.begin)).attach(
                task_text(ready.task, ready.step, context, discussion), earlier,
                partial(commit_names, self.checkouts(request.checkout), request.checkout))
            ref = self.files.put_input(key, text)
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        except (EvidenceError, InputError, GitUnavailable, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))
        try:
            return self._advance(ready, request, key, ref)
        except sqlite3.IntegrityError as error:  # caught after the rollback; every constraint is pre-checked: a schema mismatch
            return AdmitRefused("constraint", detail=why(error))
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))

    def _previous(self, request: NextStepRequest) -> tuple[sqlite3.Connection, Task, str] | AdmitRefused | AdmitUnavailable:
        """The choices, the deadline, then the previous attempt's task and the step after it; a superseded previous
        attempt is `task_attempted` before any tracker read (the transaction checks it again)."""
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        try:
            con = open_store(self.connect)
            found = task_of(con, request.previous)
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))
        step = None if found is None else next_step(found.step, True)
        if found is None or step is None or not is_agent(step) or found.end_commit is None:
            return AdmitRefused("not_advanceable")  # the check step is the checks admission's (`check_admit`)
        return (con, found, step) if found.current else AdmitRefused("task_attempted")

    def _ready(self, request: NextStepRequest) -> _Ready | AdmitRefused | AdmitUnavailable:
        """Then the checkout's repository and its free slots passing the branch rule (local reads: no slot is
        `no_free_slot` before any tracker call), then the one tracker read (still in progress for the factory's actor;
        no label)."""
        previous = self._previous(request)
        if not isinstance(previous, tuple):
            return previous
        con, found, step = previous
        free = self._free(con, request, found)
        if not isinstance(free, tuple):
            return free
        task = read_task(self.tasks, found.task_id, found.backlog, found.tracker_root)
        if not isinstance(task, TaskInspection):
            return task
        if task.status != "in_progress" or task.assignee != ACTOR:
            return AdmitRefused("claim_lost", detail=f"The tracker shows {found.task_id} {task.status or 'without status'}, "
                                f"assigned to {task.assignee or 'nobody'}")
        return _Ready(con, found, step, task, free)

    def _free(self, con: sqlite3.Connection, request: NextStepRequest, found: Task) -> tuple[Free, ...] | AdmitRefused | AdmitUnavailable:
        """The checkout is the previous attempt's repository; its free slots whose D the task branch rule passes and
        whose start (as the entry takes it) contains the previous X."""
        checked = checkout_repo(self.checkouts, request.checkout)
        if not isinstance(checked, tuple):
            return checked
        repo, repo_id = checked
        if repo_id != found.repo_id:
            return AdmitRefused("checkout", detail="The checkout is not the repository of the task's previous step")
        views = free_slots(con, repo, SlotGit(self.checkouts, self.slot_files), repo_id, self.probe)
        free = views if not isinstance(views, tuple) else branched(repo, found.task_id, views)
        return free if not isinstance(free, tuple) else _containing(repo, found, free)

    def _advance(self, ready: _Ready, request: NextStepRequest, key: AttemptKey, ref: FileRef) -> Admitted | AdmitRefused:
        """Under the write lock: the task's current attempt is still `previous` and done; the lowest observed-free slot
        still unheld; then the reservation, the slot's counter and attempt 1 of the next step starting after the previous
        X."""
        con, found, step, free = ready.con, ready.found, ready.step, ready.free
        repo_id, generation = RepoId(found.repo_id), key.reservation_generation
        with self.begin(con):
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            row: tuple[object, ...] | None = con.execute(CURRENT, (found.backlog, found.task_id)).fetchone()
            if row is None or row[0:3] != astuple(request.previous):
                return AdmitRefused("task_attempted")
            if AttemptStore(lambda: con).earlier_for(request.previous) != ready.earlier:
                return AdmitRefused("task_attempted", detail="The earlier attempt changed while the input was being prepared.")
            if not row[3] or next_step(str(row[4]), True) != step:
                return AdmitRefused("not_advanceable")
            chosen = next((slot for each in free if (slot := unheld(con, repo_id, each, generation)) is not None), None)
            if chosen is None:
                return AdmitRefused("no_free_slot")
            name, head = chosen
            reserve(con, repo_id, name, key)
            insert_attempt(
                con,
                {
                    "attempt_id": key.attempt_id,
                    "dispatch_token": key.dispatch_token,
                    "generation": generation,
                    "adapter": "beads",
                    "backlog": found.backlog,
                    "task_id": found.task_id,
                    "tracker_root": row[6],
                    "repo_id": repo_id,
                    "slot": name,
                    "step": step,
                    "input_path": ref.path,
                    "input_digest": ref.digest,
                    "schema_version": 1,
                    "model": request.setting.model,
                    "effort": request.setting.effort,
                    "access_policy": encode_policy(request.setting.access),
                    "deadline": request.deadline,
                    "number": 1,
                    "previous_attempt_id": None,
                    "repeat_reason": None,
                    "repeat_listing": None,
                    "seq": as_count(row[7]) + 1,
                    "slot_head": head,
                    "after_commit": row[5],
                    "label": row[8],
                    "harness": request.setting.harness,
                    "provider": request.setting.provider,
                },
            )
        return Admitted(key, name)


def task_of(con: sqlite3.Connection, previous: AttemptKey) -> Task | None:
    row: tuple[object, ...] | None = con.execute(
        "SELECT p.backlog,p.task_id,p.tracker_root,p.repo_id,p.step,NOT " + LATER + ",p.end_commit FROM attempt p "
        "WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?",
        astuple(previous),
    ).fetchone()
    if row is None:
        return None
    backlog, task_id, root, repo_id, step, current, end = row
    if not all(isinstance(each, str) for each in row[:5]) or not isinstance(end, (str, type(None))):
        raise sqlite3.DatabaseError("Malformed attempt row")
    return Task(str(backlog), str(task_id), str(root), str(repo_id), str(step), bool(current), end)


def _containing(repo: Repo, found: Task, free: tuple[Free, ...]) -> tuple[Free, ...] | AdmitRefused | AdmitUnavailable:
    """Read-only, before anything is reserved (the entry checks it again): the free slots, when the start every slot
    takes, the local `task/<id>`, else origin's remote-tracking one, else origin main's tip, contains the previous X."""
    after, task_id = found.end_commit or "", found.task_id
    try:
        tips = {entry.name: entry.sha for entry in repo.refs([HEADS, REMOTES, ORIGIN_MAIN])}
        tip = tips.get(f"{HEADS}/{task_id}") or tips.get(f"{REMOTES}/{task_id}") or tips.get(ORIGIN_MAIN)
        keep = free if tip is not None and not lacks(repo, after, tip) else ()
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))
    return keep or AdmitRefused("branch_moved", detail=f"task/{task_id} does not contain the previous step's commit {after}")
