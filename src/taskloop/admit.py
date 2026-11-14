"""Admit a fresh task attempt with fenced plan reuse and a tracker claim outside the transaction."""

import math
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Literal

from beads_client import BdError
from git_porcelain import GitUnavailable, NotARepo, Repo

from taskloop.admit_rows import Free, insert_attempt, issued, next_seq, reserve, task_attempted, unheld
from taskloop.agents.settings import AgentSetting, Overrides, StepSettings, apply, encode_policy
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, FileRef, SlotFiles
from taskloop.discussion import CollectDiscussion, empty, replace_block
from taskloop.drain.models import BLOCKED, ActionKind, Identity, Reason
from taskloop.drain.observe import identity
from taskloop.drain.store import DrainStore, blocked
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.earlier_input import EarlierInput, commit_names
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.factory_schema import current
from taskloop.git_views import GitProfileFiles
from taskloop.hold_store import HoldStore
from taskloop.ids import Ids
from taskloop.input_context import InputContext, InputError
from taskloop.input_context import read as read_context
from taskloop.plan_reuse import ReuseDecision
from taskloop.prepare import held_refusal, refreshed_sources, refusal_detail
from taskloop.repo import RepoId, UnsupportedCheckout, inspect_repo
from taskloop.resume_plan import ResumePlans, Selection
from taskloop.slots import Probe, SlotGit, SlotsUnavailable, SlotView, observe, unusable_text
from taskloop.steps import kind
from taskloop.task import TaskInspection, TaskInspectionError
from taskloop.task_content import TaskContentDigest

type Claim = Callable[[str, str], bool]  # (tracker root, task id): True taken, False held elsewhere, BdError unknown
type Unclaim = Callable[[str, str], bool]  # fenced to this actor's own claim; False: not released
type Tasks = Callable[[str, str, str], TaskInspection]  # (task id, backlog, tracker root)
type Refusal = Literal[
    "choices", "deadline", "expired", "task", "task_missing", "checkout", "no_free_slot", "task_attempted", "input",
    "claimed_elsewhere", "constraint",
    "not_repeatable", "repeat_cap", "branch_name", "branch_held", "branch_diverged", "branch_unpublished", "claim_lost",
    "not_advanceable", "branch_moved",
    "commit_missing", "target", "target_profile", "no_required",  # the checks admission's (`check_admit`)
    "landing", "landed",  # a checks re-run refused by the task's land candidates (`factory_schema.LANDING`)
]
NOT_CLAIMED = frozenset({"missing_binary", "version", "not_found", "lint"})  # BdError kinds where the claim certainly did not happen


@dataclass(frozen=True)
class AdmitRequest:
    """Settings and overrides are applied after step selection; `deadline` is wall-clock seconds."""

    task_id: str
    backlog: str
    tracker_root: str
    checkout: Path
    settings: StepSettings
    deadline: float
    label: str | None  # the approval label a round ingests the task under, stored on the attempt; None: started by hand
    overrides: Overrides = field(default_factory=Overrides)


@dataclass(frozen=True)
class Admitted:
    key: AttemptKey
    slot: str


@dataclass(frozen=True)
class AdmitRefused:
    reason: Refusal | Reason
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
    task: TaskInspection
    repo: Repo
    repo_id: RepoId
    earlier: EarlierAttempt | None = None
    content_digest: TaskContentDigest | None = None
    selection: Selection | None = None
    setting: AgentSetting | None = None


def why(error: BaseException) -> str:
    """The failure's type and message, bounded for a result."""
    return f"{type(error).__name__}: {error}"[:300]


def task_text(task: TaskInspection, step: str, context: InputContext, discussion: str | None = None) -> str:
    """The step kind's input for the task (its own prose, then the step's closing words), stored as the admitted input
    under its digest."""
    found = kind(step)
    text = found.input_text(task, found.rules(task.reference.task_id), context)
    return replace_block(text, empty(task, "").text if discussion is None else discussion)


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
        slot_files: SlotFiles,
        me: Callable[[], Identity | None] = identity,
        *, ids: Ids, discussion: CollectDiscussion = empty,
    ) -> None:
        """Observe free slots through their lock probe and pinned pointer check."""
        self.ids = ids
        self.discussion = discussion
        self.me = me
        self.connect, self.begin, self.files, self.tasks, self.checkouts = connect, begin, files, tasks, checkouts
        self.claim, self.unclaim, self.clock, self.probe, self.slot_files = claim, unclaim, clock, probe, slot_files

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
        inputs = self._input(prepared, free, con)
        if not isinstance(inputs, tuple):
            return inputs
        prepared, key, ref = inputs
        return self._claimed(con, prepared, free, key, ref)

    def _input(self, prepared: _Prepared, free: tuple[Free, ...], con: sqlite3.Connection
               ) -> tuple[_Prepared, AttemptKey, FileRef] | AdmitRefused | AdmitUnavailable:
        request = prepared.request
        try:
            generation = issued(con, prepared.repo_id, tuple(each.name for each in free)) + 1
            reader = AttemptStore(self.connect, self.begin)
            earlier = reader.earlier(str(prepared.repo_id), request.backlog, request.task_id, prepared.request.tracker_root)
            key = AttemptKey(self.ids.hex(), self.ids.token(16), generation)  # the key names the evidence directory
            context = read_context(GitProfileFiles(request.checkout, self.checkouts), free[0].source)
            discussion = self.discussion(prepared.task, prepared.request.tracker_root)
            selection = ResumePlans(reader, self.checkouts).select(
                str(prepared.repo_id), request.backlog, request.task_id, prepared.request.tracker_root,
                request.checkout, free[0].source, discussion.digest)
            if selection.decision is ReuseDecision.UNAVAILABLE:
                return AdmitUnavailable("git", detail=selection.explanation)
            prepared = replace(prepared, earlier=earlier, content_digest=discussion.digest, selection=selection,
                               setting=apply(request.settings.for_step(selection.step), request.overrides))
            text = EarlierInput(reader, self.files, HoldStore(self.connect, self.begin)).attach(
                task_text(prepared.task, selection.step, context, discussion.text), earlier,
                partial(commit_names, prepared.repo, request.checkout))
            ref = self.files.put_input(key, text)
        except (sqlite3.Error, StoreUnavailable) as error:
            return AdmitUnavailable("store", detail=why(error))
        except (EvidenceError, InputError, UnicodeError, OSError) as error:
            return AdmitRefused("input", detail=why(error))
        except ValueError as error:
            return AdmitRefused("choices", detail=why(error))
        return prepared, key, ref

    def _prepare(self, request: AdmitRequest) -> _Prepared | AdmitRefused | AdmitUnavailable:
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        task = read_task(self.tasks, request.task_id, request.backlog, request.tracker_root)
        if not isinstance(task, TaskInspection):
            return task
        try:
            tracker = Path(request.tracker_root).expanduser().resolve()
        except (RuntimeError, OSError) as error:
            return AdmitRefused("task", detail=why(error))
        found = checkout_repo(self.checkouts, request.checkout)
        if not isinstance(found, tuple):
            return found
        # the root as resolved now is the one claimed, stored and renewed (.4.3.1.9)
        return _Prepared(replace(request, tracker_root=str(tracker)), task, *found)

    def _observe(self, prepared: _Prepared) -> tuple[sqlite3.Connection, tuple[SlotView, ...]] | AdmitRefused | AdmitUnavailable:
        """An attempted task, then no free slot, refuse before any effect; store failure never counts as free."""
        try:
            con = open_store(self.connect)
            if task_attempted(con, prepared.request.backlog, prepared.request.task_id):
                return AdmitRefused("task_attempted")
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))
        free = free_slots(con, prepared.repo, SlotGit(self.checkouts, self.slot_files), prepared.repo_id, self.probe)
        return (con, free) if isinstance(free, tuple) else free

    def _claimed(self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[Free, ...], key: AttemptKey, ref: FileRef) -> AdmitResult:
        request, owner = prepared.request, self.me()
        if owner is None:
            return AdmitUnavailable("store", detail="The admission owner's identity cannot be established")
        drain = DrainStore(lambda: con, ids=self.ids)
        try:
            action = drain.authorize(ActionKind.CLAIM, owner, subject=request.task_id, backlog=request.backlog,
                                     tracker_root=request.tracker_root)
        except sqlite3.IntegrityError:
            return AdmitRefused("task_attempted", detail="Another admission already owns this task's pending claim.")
        if action is None:
            return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
        result = self._claim_then_admit(con, prepared, free, key, ref)
        if isinstance(result, Admitted) or not result.claim_leaked:
            drain.finish(action)
        else:
            drain.uncertain(action)
        return result

    def _claim_then_admit(self, con: sqlite3.Connection, prepared: _Prepared, free: tuple[Free, ...], key: AttemptKey,
                         ref: FileRef) -> AdmitResult:
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
        except (sqlite3.Error, StoreUnavailable) as error:
            result = AdmitUnavailable("store", detail=why(error))
        except BaseException:
            self._compensate(request)
            raise
        if isinstance(result, Admitted):
            return result
        return replace(result, claim_leaked=self._compensate(request))

    def _compensate(self, request: AdmitRequest) -> bool:
        """Return a claim only when no attempt holds it; True when the release is uncertain. Never force or retry it."""
        try:
            if task_attempted(open_store(self.connect), request.backlog, request.task_id):
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
        """Recheck task and plan evidence under the write lock, then reserve a slot and insert the attempt."""
        request, repo_id, generation = prepared.request, prepared.repo_id, key.reservation_generation
        selection, setting = prepared.selection, prepared.setting
        if selection is None or setting is None:
            raise StoreUnavailable("The admission choices were not prepared.")
        with self.begin(con):
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            if task_attempted(con, request.backlog, request.task_id):
                return AdmitRefused("task_attempted")
            if AttemptStore(lambda: con).earlier(str(repo_id), request.backlog, request.task_id,
                                               request.tracker_root) != prepared.earlier:
                return AdmitRefused("task_attempted", detail="The earlier attempt changed while the input was being prepared.")
            if not ResumePlans(AttemptStore(lambda: con), self.checkouts).unchanged(
                    selection, str(repo_id), request.backlog, request.task_id, request.tracker_root, prepared.content_digest):
                return AdmitRefused("task_attempted", detail="The plan evidence changed while the input was being prepared.")
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
                    "generation": key.reservation_generation,
                    "adapter": "beads",
                    "backlog": request.backlog,
                    "task_id": request.task_id,
                    "tracker_root": request.tracker_root,
                    "repo_id": repo_id,
                    "slot": name,
                    "step": selection.step,
                    "input_path": ref.path,
                    "input_digest": ref.digest,
                    "schema_version": 1,
                    "model": setting.model, "effort": setting.effort,
                    "compaction_token_limit": setting.compaction_token_limit, "deadline": request.deadline,
                    "access_policy": encode_policy(setting.access),
                    "number": 1,
                    "previous_attempt_id": None,
                    "repeat_reason": None,
                    "repeat_listing": None,
                    "seq": next_seq(con, request.backlog, request.task_id),
                    "slot_head": head,
                    "after_commit": free[0].source if selection.decision is ReuseDecision.REUSE else None,
                    "label": request.label,
                    "harness": setting.harness,
                    "provider": setting.provider,
                },
                prepared.content_digest,
            )
        return Admitted(key, name)


def read_task(tasks: Tasks, task_id: str, backlog: str, tracker_root: str) -> TaskInspection | AdmitRefused | AdmitUnavailable:
    """The one tracker read of an admission (`bd show`): the task's prose for the input, its status and assignee."""
    try:
        return tasks(task_id, backlog, tracker_root)
    except TaskInspectionError as error:
        if error.kind == "tracker_unavailable":
            return AdmitUnavailable("tracker", detail=why(error))
        if error.kind == "not_found":
            gone = f"{task_id} is gone from the tracker; `tl step release --abandon {task_id}` clears its attempt"
            return AdmitRefused("task_missing", detail=gone)
        return AdmitRefused("task", detail=f"{error.kind}: {why(error)}")


def checkout_repo(checkouts: Checkouts, path: Path) -> tuple[Repo, RepoId] | AdmitRefused | AdmitUnavailable:
    """The person's checkout, resolved, and the repository it belongs to; read-only."""
    try:
        checkout = path.expanduser().resolve()
        repo = checkouts(checkout)
        return repo, inspect_repo(repo, checkout).repo_id
    except (UnsupportedCheckout, RuntimeError, OSError) as error:
        return AdmitRefused("checkout", detail=why(error))
    except NotARepo:  # a missing path or a directory outside any repository: the person's input, not a transient Git fault
        return AdmitRefused("checkout", detail=f"{path} is not a Git repository checkout (--checkout names its root).")
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))


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
    con: sqlite3.Connection, repo: Repo, git: SlotGit, repo_id: RepoId, probe: Probe
) -> tuple[SlotView, ...] | AdmitRefused | AdmitUnavailable:
    """The observed-free slots, read-only; a store failure never counts as free."""
    try:
        views = observe(con, repo, git, repo_id, probe)
    except (sqlite3.Error, SlotsUnavailable) as error:
        return AdmitUnavailable("store", detail=why(error))
    if any(view.reason == "store_unavailable" for view in views):
        return AdmitUnavailable("store", detail="Reservations unreadable")
    free = tuple(view for view in views if view.state == "free")
    return free or AdmitRefused("no_free_slot", views, detail=unusable_text(views))


def branched(repo: Repo, task_id: str, free: tuple[SlotView, ...]) -> tuple[Free, ...] | AdmitRefused | AdmitUnavailable:
    """Refresh origin main before any file, claim or row, then select eligible free slots and their park destination."""
    try:
        heads, found, park_commit = refreshed_sources(repo, task_id, tuple(view.path for view in free))
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))
    if isinstance(found, str):
        held, detail = held_refusal(repo, task_id, free) if found == "branch_held" else ((), refusal_detail(found, task_id))
        return AdmitRefused(found, held, detail=detail)
    passing = tuple(Free(view.name, head, found.start, park_commit) for view in free
                    if park_commit is not None and (head := heads.get(view.path)) is not None and head in found.passing)
    return passing or AdmitRefused("no_free_slot")
