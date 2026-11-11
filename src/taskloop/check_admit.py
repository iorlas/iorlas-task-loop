"""Admit a checks attempt (tl-8bh9.14.6 section 5): the check step after a done implement attempt (an advance, number 1),
or again on the same X after its latest checks attempt concluded `failed` and was released (a re-run, number + 1). It
claims nothing, writes no input file and runs nothing; the checks entry (`check_entry`) does the rest.

Every read before any effect, in order: the deadline; the implement attempt still the task's current one and done
(verified, released with its claim kept, published at X; else `not_advanceable`, also while the task's abandon is half
done) and the number its checks attempts give; the checkout's repository is the attempt's; X readable (`commit_missing`)
and still on the task's branch, the local `task/<id>` else the remote-tracking one (`branch_moved`); the required names
from the profile at the person's local `refs/heads/main` (O1: `target`, `target_profile`, `no_required`), each with the
argv digest of its check there; a free slot (no branch rule: the slot takes X detached); one tracker read (`claim_lost`
unless in progress for taskloop; no label, D3). Then one write transaction re-reads the attempt and the number, reserves
the lowest observed-free slot still unheld (`admit.reserve`) and inserts the row (`check_store.insert`: D is the slot's
HEAD). A lost race on the number is `task_attempted`: the caller launches the winner with the checks launcher.
"""

import secrets
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import astuple, dataclass
from pathlib import Path
from uuid import uuid4

from git_porcelain import GitUnavailable, Repo

from taskloop.admit import (
    AdmitRefused,
    AdmitResult,
    Admitted,
    AdmitUnavailable,
    Free,
    Tasks,
    checkout_repo,
    deadline_refusal,
    free_slots,
    issued,
    open_store,
    read_task,
    reserve,
    unheld,
    why,
)
from taskloop.admit_chain import CURRENT, Task, task_of
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey, Checkouts, SlotFiles
from taskloop.check_status import HALF_DONE
from taskloop.check_store import ChecksAdmitted, Required, insert
from taskloop.checks import argv_digest, main_seen
from taskloop.prepare import HEADS, REMOTES, lacks
from taskloop.profile import Profile, ProfileFiles, Refused, Unavailable, read_profile
from taskloop.repo import RepoId
from taskloop.slots import Probe, SlotGit, SlotView
from taskloop.steps import CHECK, following
from taskloop.task import TaskInspection
from taskloop.tracker import ACTOR

type Profiles = Callable[[Path], ProfileFiles]  # the person's checkout: a file at a commit (`git_views.GitProfileFiles`)
TARGET = "main"  # the only land target M2 checks against (another one is B6's)
# The latest checks attempt of one implement attempt: what decides the number the next one takes.
LATEST = """SELECT number,phase,conclusion,released_at IS NOT NULL,abandoned FROM checks_attempt WHERE after_attempt_id=?
ORDER BY number DESC LIMIT 1"""


@dataclass(frozen=True)
class ChecksRequest:
    """`previous`: the task's done implement attempt. `number`: the checks attempt the caller read as next (1 for the
    advance, the failed latest one's + 1 for a re-run); the store deciding another number is `task_attempted` (a
    concurrent start changed it since)."""

    previous: AttemptKey
    checkout: Path
    deadline: float
    number: int


@dataclass(frozen=True)
class _Ready:
    con: sqlite3.Connection
    found: Task
    target: str
    required: Required
    free: tuple[Free, ...]


def next_number(con: sqlite3.Connection, previous: AttemptKey) -> int | AdmitRefused:
    """Under any read: the implement attempt `previous` is the task's current attempt and done, and the number of its
    next checks attempt: 1 when it has none, the latest + 1 after a concluded `failed`, released, not abandoned one.
    A latest one abandoned is `not_advanceable` (the abandon is half done); any other is `task_attempted`."""
    found = task_of(con, previous)
    row = None if found is None else con.execute(CURRENT, (found.backlog, found.task_id)).fetchone()
    if row is None or row[0:3] != astuple(previous) or not row[3] or following(str(row[4])) != CHECK:
        return AdmitRefused("not_advanceable", detail="The implement attempt is not the task's current, done (verified, released "
                            "with its claim kept, published) attempt")
    latest: tuple[object, ...] | None = con.execute(LATEST, (previous.attempt_id,)).fetchone()
    if latest is None:
        return 1
    number, phase, conclusion, released, abandoned = latest
    if abandoned:
        return AdmitRefused("not_advanceable", detail=HALF_DONE)
    if phase == "concluded" and conclusion == "failed" and released and isinstance(number, int):
        return number + 1
    return AdmitRefused("task_attempted", detail="The task's latest checks attempt is current")


class ChecksAdmission:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
        tasks: Tasks,
        checkouts: Checkouts,
        clock: Callable[[], float],
        probe: Probe,
        slot_files: SlotFiles,
        profiles: Profiles,
    ) -> None:
        """The ports of an advance (`admit_chain.NextAdmission`) without the input files, plus the profile port on the
        person's checkout."""
        self.connect, self.begin, self.tasks, self.checkouts, self.clock = connect, begin, tasks, checkouts, clock
        self.probe, self.slot_files, self.profiles = probe, slot_files, profiles

    def admit_checks(self, request: ChecksRequest) -> AdmitResult:
        ready = self._ready(request)
        if not isinstance(ready, _Ready):
            return ready
        repo_id = RepoId(ready.found.repo_id)
        try:
            key = AttemptKey(uuid4().hex, secrets.token_hex(16), issued(ready.con, repo_id, tuple(each.name for each in ready.free)) + 1)
            return self._commit(ready, request, key)
        except StoreRefused as error:  # raised under the write lock, after the rollback: the number was taken meanwhile
            return AdmitRefused("task_attempted", detail=str(error))
        except sqlite3.IntegrityError as error:  # every constraint is pre-checked: a schema mismatch
            return AdmitRefused("constraint", detail=why(error))
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))

    def _previous(self, request: ChecksRequest) -> tuple[sqlite3.Connection, Task] | AdmitRefused | AdmitUnavailable:
        """Steps 1-2: the deadline, then the implement attempt and the number."""
        refused = deadline_refusal(self.clock, request.deadline)
        if refused is not None:
            return refused
        try:
            con = open_store(self.connect)
            number, found = next_number(con, request.previous), task_of(con, request.previous)
        except sqlite3.Error as error:
            return AdmitUnavailable("store", detail=why(error))
        if isinstance(number, AdmitRefused):
            return number
        if number != request.number or found is None:
            return AdmitRefused("task_attempted", detail=f"The next checks attempt is number {number}, not {request.number}")
        return con, found

    def _ready(self, request: ChecksRequest) -> _Ready | AdmitRefused | AdmitUnavailable:
        """Steps 2-6: the implement attempt, the candidate (checkout, X, required names), the free slots, then the one
        tracker read."""
        previous = self._previous(request)
        if not isinstance(previous, tuple):
            return previous
        con, found = previous
        candidate = self._candidate(request, found)
        if not isinstance(candidate, tuple):
            return candidate
        repo, target, required = candidate
        views = free_slots(con, repo, SlotGit(self.checkouts, self.slot_files), RepoId(found.repo_id), self.probe)
        free = views if not isinstance(views, tuple) else _heads(repo, views)
        if not isinstance(free, tuple):
            return free
        return self._lost(found) or _Ready(con, found, target, required, free)

    def _candidate(self, request: ChecksRequest, found: Task) -> tuple[Repo, str, Required] | AdmitRefused | AdmitUnavailable:
        """Steps 2-4: the checkout is the attempt's repository; X readable and on the task's branch; the required names."""
        checked = checkout_repo(self.checkouts, request.checkout)
        if not isinstance(checked, tuple):
            return checked
        repo, repo_id = checked
        if repo_id != found.repo_id:
            return AdmitRefused("checkout", detail="The checkout is not the repository of the task's implement attempt")
        required = _on_branch(repo, found) or self._required(repo, request.checkout.expanduser().resolve())
        return required if not isinstance(required, tuple) else (repo, *required)

    def _required(self, repo: Repo, checkout: Path) -> tuple[str, Required] | AdmitRefused | AdmitUnavailable:
        """Step 4 (O1): the target (`main`'s commit now) and its profile's required names, each with its check's argv
        digest there; a name the target's own checks do not define is that profile's `required_undefined`."""
        try:
            target = main_seen(repo)
        except GitUnavailable as error:
            return AdmitUnavailable("git", detail=why(error))
        if target is None:
            return AdmitRefused("target", detail="The checkout has no local branch `main` to read the required checks from")
        profile = read_profile(self.profiles(checkout), target)
        if isinstance(profile, Unavailable):
            return AdmitUnavailable("git", detail=profile.detail)
        return _named(target, profile)

    def _lost(self, found: Task) -> AdmitRefused | AdmitUnavailable | None:
        """Step 6: one tracker read; the task must still be in progress for taskloop (no label, D3)."""
        task = read_task(self.tasks, found.task_id, found.backlog, found.tracker_root)
        if not isinstance(task, TaskInspection):
            return task
        if task.status != "in_progress" or task.assignee != ACTOR:
            return AdmitRefused("claim_lost", detail=f"The tracker shows {found.task_id} {task.status or 'without status'}, "
                                f"assigned to {task.assignee or 'nobody'}")
        return None

    def _commit(self, ready: _Ready, request: ChecksRequest, key: AttemptKey) -> Admitted | AdmitRefused:
        """Step 7, under the write lock: the attempt and the number again, the lowest observed-free slot still unheld,
        then the reservation, the slot's counter and the row."""
        con, repo_id = ready.con, RepoId(ready.found.repo_id)
        with self.begin(con):
            number = next_number(con, request.previous)
            if isinstance(number, AdmitRefused):
                return number
            if number != request.number:
                return AdmitRefused("task_attempted", detail=f"The next checks attempt is number {number}, not {request.number}")
            generation = key.reservation_generation
            chosen = next((slot for each in ready.free if (slot := unheld(con, repo_id, each, generation)) is not None), None)
            if chosen is None:
                return AdmitRefused("no_free_slot")
            name, head = chosen
            reserve(con, repo_id, name, key)
            insert(con, ChecksAdmitted(key, request.previous.attempt_id, number, name, head, ready.target, ready.required,
                                       request.deadline))
        return Admitted(key, name)


def _named(target: str, profile: Profile | Refused) -> tuple[str, Required] | AdmitRefused:
    """The profile at `main`: refused (`target_profile`), naming another target (`target`), requiring nothing
    (`no_required`) or a name its own checks do not define (`target_profile`); else each required name with its digest."""
    if isinstance(profile, Refused):
        return AdmitRefused("target_profile", detail=f"{profile.reason}: {profile.detail}"[:300])
    if profile.target != TARGET:
        return AdmitRefused("target", detail=f"The profile at main names the target {profile.target}, not main")
    if not profile.required:
        return AdmitRefused("no_required", detail="The profile at main requires no check: nothing would decide a pass")
    argv = {check.name: check.argv for check in profile.checks}
    undefined = [name for name in profile.required if name not in argv]
    if undefined:
        return AdmitRefused("target_profile", detail=f"required_undefined: {', '.join(undefined)} at main")
    return target, tuple((name, argv_digest(argv[name])) for name in profile.required)


def _on_branch(repo: Repo, found: Task) -> AdmitRefused | AdmitUnavailable | None:
    """Step 3: X readable (`commit_missing`), then contained by the local `task/<id>`, else the remote-tracking one
    (`branch_moved`). The checks run on X itself, never the tip."""
    x, task_id = found.end_commit or "", found.task_id
    try:
        if repo.tree(f"{x}^{{commit}}") is None:
            return AdmitRefused("commit_missing", detail=f"The implement attempt's commit {x} is not in the repository")
        tips = {entry.name: entry.sha for entry in repo.refs([HEADS, REMOTES])}
        tip = tips.get(f"{HEADS}/{task_id}") or tips.get(f"{REMOTES}/{task_id}")
        moved = tip is None or lacks(repo, x, tip)
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))
    return AdmitRefused("branch_moved", detail=f"task/{task_id} does not contain the implement attempt's commit {x}") if moved else None


def _heads(repo: Repo, views: tuple[SlotView, ...]) -> tuple[Free, ...] | AdmitRefused | AdmitUnavailable:
    """Step 5: each observed-free slot with its HEAD (D, where the release parks it); no branch rule."""
    try:
        heads = {info.path: info.head for info in repo.worktrees()}
    except GitUnavailable as error:
        return AdmitUnavailable("git", detail=why(error))
    found = tuple(Free(view.name, head) for view in views if (head := heads.get(view.path)) is not None)
    return found or AdmitRefused("no_free_slot")
