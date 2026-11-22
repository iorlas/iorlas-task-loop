"""Continue a claimed task: prepare input, then admit a repeat, repair or advance without claiming again."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
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
    open_store,
    read_task,
    why,
)
from taskloop.admit_rows import Task
from taskloop.admit_store import (
    copied_pin,
    current,
    insert_attempt,
    issued,
    named_pin,
    reserve,
    stored_pin,
    task_of,
    transfer,
    unheld,
)
from taskloop.admit_store import previous as read_previous
from taskloop.agents.settings import AgentSetting, Overrides, choose, encode_policy
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, FileRef, RepeatReason, SlotFiles
from taskloop.discussion import CollectDiscussion, empty
from taskloop.drain.models import BLOCKED, Reason
from taskloop.drain.store import blocked
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.earlier_input import EarlierInput, commit_names
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.git_views import GitProfileFiles
from taskloop.hold_store import HoldStore
from taskloop.ids import Ids
from taskloop.input_context import InputError
from taskloop.input_context import read as read_context
from taskloop.prepare import HEADS, ORIGIN_MAIN, REMOTES, lacks
from taskloop.repo import RepoId
from taskloop.slots import Probe, SlotGit
from taskloop.step import ATTEMPTS, Step
from taskloop.steps import next_step
from taskloop.task import TaskInspection
from taskloop.task_content import TaskContentDigest
from taskloop.task_input import task_text
from taskloop.tracker import ACTOR
from taskloop.workflow_read import Pin, WorkflowRefusal


@dataclass(frozen=True)
class RepeatRequest:
    """The step's next attempt: `previous` is the current attempt it repeats, `text` its complete admitted input."""

    previous: AttemptKey
    text: str
    deadline: float
    reason: RepeatReason
    listing: tuple[str, ...] = ()  # what the failed factory commit listed; stored with the repeat, the factory commit's typed result
    content_digest: TaskContentDigest | None = None


class _Lost(Exception):
    """No reservation row moved from the previous attempt: roll the new attempt back."""


class ChainAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[object]],
        files: EvidenceFiles,
        clock: Callable[[], float],
        checkouts: Checkouts,
        slot_files: SlotFiles,
        *,
        ids: Ids,
        engine: str,
    ) -> None:
        self.ids, self.engine = ids, engine
        self.connect, self.begin, self.files, self.clock = connect, begin, files, clock
        self.checkouts, self.slot_files = checkouts, slot_files

    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable:
        """Write input first; atomically recheck, insert the repeat and transfer custody, fencing the previous attempt."""
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
            text = (
                request.text
                if earlier is None
                else EarlierInput(reader, self.files, HoldStore(self.connect, self.begin)).attach_slot(
                    request.text, earlier, self.checkouts, self.slot_files
                )
            )
            ref = self.files.put_input(key, text)
            return self._takeover(open_store(self.connect), request, key, ref, earlier)
        except (_Lost, sqlite3.IntegrityError) as error:
            return AdmitRefused("task_attempted", detail=why(error))
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        except (EvidenceError, InputError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))

    def _takeover(
        self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef, earlier: EarlierAttempt | None
    ) -> Admitted | AdmitRefused:
        with self.begin(con):
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            if AttemptStore(lambda: con).earlier_for(request.previous) != earlier:
                return AdmitRefused("task_attempted", detail="The earlier attempt changed while the input was being prepared.")
            return self._takeover_open(con, request, key, ref)

    def _takeover_open(self, con: sqlite3.Connection, request: RepeatRequest, key: AttemptKey, ref: FileRef) -> Admitted | AdmitRefused:
        previous = request.previous
        row = read_previous(con, previous)
        if row is None:
            return AdmitRefused("not_repeatable")
        if row.repeated:
            return AdmitRefused("task_attempted")
        number = row.number
        if number >= ATTEMPTS:
            return AdmitRefused("repeat_cap")
        if not row.repeatable:
            return AdmitRefused("not_repeatable")
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        if row.step is Step.PLAN and request.content_digest is None:
            raise InputError("A plan repeat requires freshly collected task-content evidence")
        insert_attempt(
            con,
            {
                "attempt_id": key.attempt_id,
                "dispatch_token": key.dispatch_token,
                "generation": key.reservation_generation,
                "adapter": row.adapter,
                "backlog": row.backlog,
                "task_id": row.task_id,
                "tracker_root": row.tracker_root,
                "repo_id": row.repo_id,
                "slot": row.slot,
                "input_path": ref.path,
                "input_digest": ref.digest,
                "schema_version": 1,
                "model": row.model,
                "effort": row.effort,
                "access_policy": row.access_policy,
                "deadline": request.deadline,
                "number": number + 1,
                "previous_attempt_id": previous.attempt_id,
                "repeat_reason": request.reason,
                "repeat_listing": json.dumps(request.listing),
                "seq": row.seq + 1,
                "slot_head": row.slot_head,
                "step": row.step,
                "harness": row.harness,
                "provider": row.provider,
                "engine_digest": self.engine,
                "admitted_at": self.clock(),
                **copied_pin(con, previous.attempt_id),
                "declared_start": 0,
                "compaction_token_limit": row.compaction_token_limit,
                "after_commit": None,
                "label": row.label,  # a repeat starts at E, the chain's own
            },
            request.content_digest,
        )
        if not transfer(con, previous, key, row.repo_id, row.slot):
            raise _Lost
        return Admitted(key, row.slot)


# The task's current attempt (its highest `seq`) under the write lock: its key, whether it is done (committed, released
# settled with the claim kept, its X published), its step, X, tracker root, order and label (the next step's copy).
@dataclass(frozen=True)
class NextStepRequest:
    """Attempt 1 of the step after `previous`'s; every choice is the caller's (no label: claimed work is not ingested)."""

    previous: AttemptKey
    checkout: Path
    setting: AgentSetting  # the machine configuration's for the next step; the workflow's keys and `overrides` are applied on it
    deadline: float
    overrides: Overrides = field(default_factory=Overrides)


@dataclass(frozen=True)
class _Ready:
    """Everything an advance read before any effect."""

    con: sqlite3.Connection
    found: Task
    step: Step
    task: TaskInspection
    free: tuple[Free, ...]
    earlier: EarlierAttempt | None = None


class NextAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[object]],
        files: EvidenceFiles,
        tasks: Tasks,
        checkouts: Checkouts,
        clock: Callable[[], float],
        probe: Probe,
        slot_files: SlotFiles,
        *,
        ids: Ids,
        engine: str,
        discussion: CollectDiscussion = empty,
    ) -> None:
        """The ports of a fresh admission (`admit.AttemptAdmission`) without the claim: an advance never claims."""
        self.ids, self.engine = ids, engine
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
            files = GitProfileFiles(request.checkout, self.checkouts)
            context, pin = read_context(files, ready.free[0].source), stored_pin(ready.con, request.previous.attempt_id)
            discussion = self.discussion(ready.task, found.tracker_root)
            reader = AttemptStore(self.connect, self.begin)
            earlier = reader.earlier_for(request.previous)
            ready = replace(ready, earlier=earlier)
            setting = choose(request.setting, pin.workflow.table(ready.step).agent, request.overrides, ready.step)
            text = EarlierInput(reader, self.files, HoldStore(self.connect, self.begin)).attach(
                task_text(ready.task, ready.step, context, pin.workflow, discussion.text),
                earlier,
                partial(commit_names, self.checkouts(request.checkout), request.checkout),
            )
            ref = self.files.put_input(key, text)
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        except (WorkflowRefusal, EvidenceError, InputError, GitUnavailable, UnicodeError, OSError) as error:
            return AdmitRefused("workflow" if isinstance(error, WorkflowRefusal) else "input", detail=why(error))
        except ValueError as error:  # the workflow's or a flag's agent choice is invalid
            return AdmitRefused("choices", detail=why(error))
        return self._advanced(ready, request, key, ref, pin, setting)

    def _advanced(
        self, ready: _Ready, request: NextStepRequest, key: AttemptKey, ref: FileRef, pin: Pin, setting: AgentSetting
    ) -> Admitted | AdmitRefused | AdmitUnavailable:
        try:
            return self._advance(ready, request, key, ref, pin, setting)
        except sqlite3.IntegrityError as error:  # caught after the rollback; every constraint is pre-checked: a schema mismatch
            return AdmitRefused("constraint", detail=why(error))
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))

    def _previous(self, request: NextStepRequest) -> tuple[sqlite3.Connection, Task, Step] | AdmitRefused | AdmitUnavailable:
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
        if found is None or not isinstance(step, Step) or found.end_commit is None:
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
            return AdmitRefused(
                "claim_lost",
                detail=f"The tracker shows {found.task_id} {task.status or 'without status'}, assigned to {task.assignee or 'nobody'}",
            )
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

    def _advance(
        self, ready: _Ready, request: NextStepRequest, key: AttemptKey, ref: FileRef, pin: Pin, setting: AgentSetting
    ) -> Admitted | AdmitRefused:
        """Under the write lock: the task's current attempt is still `previous` and done; the lowest observed-free slot
        still unheld; then the reservation, the slot's counter and attempt 1 of the next step starting after the previous
        X."""
        con, found, step, free = ready.con, ready.found, ready.step, ready.free
        repo_id, generation = RepoId(found.repo_id), key.reservation_generation
        with self.begin(con):
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            row = current(con, found.backlog, found.task_id)
            if row is None or row.key != request.previous:
                return AdmitRefused("task_attempted")
            if AttemptStore(lambda: con).earlier_for(request.previous) != ready.earlier:
                return AdmitRefused("task_attempted", detail="The earlier attempt changed while the input was being prepared.")
            if not row.done or next_step(row.step, True) != step:
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
                    "tracker_root": row.tracker_root,
                    "repo_id": repo_id,
                    "slot": name,
                    "step": step,
                    "input_path": ref.path,
                    "input_digest": ref.digest,
                    "schema_version": 1,
                    "model": setting.model,
                    "effort": setting.effort,
                    "compaction_token_limit": setting.compaction_token_limit,
                    "access_policy": encode_policy(setting.access),
                    "deadline": request.deadline,
                    "number": 1,
                    "previous_attempt_id": None,
                    "repeat_reason": None,
                    "repeat_listing": None,
                    "seq": row.seq + 1,
                    "slot_head": head,
                    "after_commit": row.end_commit,
                    "label": row.label,
                    "harness": setting.harness,
                    "provider": setting.provider,
                    "engine_digest": self.engine,
                    "admitted_at": self.clock(),
                    **named_pin(pin),
                    "declared_start": 0,
                },
            )
        return Admitted(key, name)


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
