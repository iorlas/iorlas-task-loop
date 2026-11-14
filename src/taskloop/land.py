"""`tl step land TASK` (tl-8bh9.14.8): one application operation, `land(ports, request)`, run by the person's command and,
under the profile's `land: auto`, by a round (`round_land`, tl-8bh9.14.136); never by an entry (`entries-never-land`). It
squashes the checked X onto origin's
`main` at O as one commit S (Git objects only, no checkout written), validates S in a free slot in the foreground when
S's tree is not X's or `main`'s required names changed, and delivers S to origin's `main` by `land_push`'s one rule
(never forced), then closes the task in the person's local tracker (`land_close`: push first, then `bd close`; never
synced). A rerun does only what is missing: a delivered candidate goes straight to the close, a closed one answers
`already_landed` with no Git or tracker call. `--summary` (`land_summary`) makes S in Git objects only and reports the
facts: no candidate, reservation, push or close.

Every read before any effect, in order (section 4): `--minutes`; this process's environment does not carry the agent's
push bar (`push_barred`); the task's current attempt a done implement attempt (`not_done`); its latest checks attempt
concluded `passed`, released, not abandoned (`not_checked`; with `--no-change` any conclusion); the latest land
candidate of it, which decides where to resume (one still holding its slot after its validation is released first;
delivered answers at once); the checkout is the attempt's repository, `origin` exists
(`no_remote`; trusted as configured); X still the task's work: the local `task/<id>` (else the remote-tracking one) and origin's
are exactly X (`branch_moved`; skipped with `--no-change`), X readable (`commit_missing`), origin has `main`
(`target`); one tracker read (`claim_lost`; `closed`, unless origin shows a pushable candidate already delivered).

A new candidate (section 5): the bounded fetch of origin's `main` (O), the profile at O (`target_profile`, `target`,
`no_required`), `Repo.squash` (`conflict`), then S's tree listing against X's (same tree) and O's (`no_change`, or
`changes` with `--no-change`), and the required names at O against the checks attempt's. Inserted with its slot's
reservation in one transaction (`land_store.insert`: `landing` when another land won) when it validates, else with
`same_tree` (or `no_change`, delivered at insert). Its validation and the delivery are `land_check` and `land_push`.
"""

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal

from git_porcelain import GitUnavailable, MissingRemote

from taskloop.admit import AdmitRefused, AdmitUnavailable, checkout_repo, open_store, read_task
from taskloop.admit_chain import CURRENT, task_of
from taskloop.agent_credentials import PUSH_REFUSED
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.check_status import latest
from taskloop.check_store import ChecksRow
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import BLOCKED, ActionKind, Reason
from taskloop.land_check import LandPorts, inserted, released, validated
from taskloop.land_close import closed
from taskloop.land_gate import Gate, gate_of
from taskloop.land_push import REMOTE, Delivered, Origin, Withdrawn, deliver, observed, remote_tips, withdraw
from taskloop.land_store import LandRow
from taskloop.land_summary import LandSummary, summarized
from taskloop.land_target import fetched_target, gated, made_s, squashed_onto
from taskloop.operations import Failed, deadline_after, minutes_refused
from taskloop.prepare import HEADS, REMOTES
from taskloop.steps import CHECK, following
from taskloop.task import TaskInspection
from taskloop.tracker import ACTOR

BAR: Final = f"url.{PUSH_REFUSED}.pushinsteadof"  # the agent's push bar (`agent_credentials.push_bar`), as Git reads keys
SHOW: Final = "`tl step show TASK` names the next step."


NEEDS_MINUTES = Failed("refused", "minutes", "--minutes is required here: S must be validated (main moved, its required names changed, or "
                       "a pending candidate resumes). Rerun with --minutes N; a candidate that origin's move superseded stays recorded so.")


@dataclass(frozen=True)
class LandRequest:
    """`minutes`: the validation's deadline from now, needed only when a block runs (`NEEDS_MINUTES`); `withdraw` gives up a validated,
    undelivered candidate; `no_change` accepts main already holding X's changes."""

    backlog: str
    task_id: str
    checkout: Path
    minutes: int | None
    mode: Literal["land", "summary", "withdraw"] = "land"
    no_change: bool = False
    accept: bool = False  # `--accept-gate-changes`: S may change what decides a pass (`land_gate`)


type How = Literal["pushed", "already_pushed", "no_change", "delivered", "already_landed"]


@dataclass(frozen=True)
class Landed:
    """The task's candidate delivered and, but from `--withdraw`, its task closed (`row.close`): `how` is `pushed` (this
    call pushed S), `already_pushed` (origin was found to hold it), `no_change` (main already held X's changes),
    `delivered` (the delivery recorded before this call, the close made now) or `already_landed` (delivered and closed
    before this call: nothing called); `release` is the word of a slot release this call ran (None: none)."""

    row: LandRow
    how: How
    release: str | None = None
    gate: Gate | None = None  # with `--accept-gate-changes`: what the pushed S changed in the gate (`land_gate`), read after the push


type LandResult = Landed | Withdrawn | LandSummary | Failed


@dataclass(frozen=True)
class _Task:
    """What section 4 steps 3-5 read: the done implement attempt, its latest checks attempt and its latest candidate."""

    implement: AttemptKey
    checks: ChecksRow
    candidate: LandRow | None
    title: str = ""  # the tracker's, read in step 8: S's subject


def _barred(environ: Mapping[str, str]) -> Failed | None:
    """Step 1: the agent's push bar among this process's Git env-config entries (an accident, not a boundary)."""
    if any(name.startswith("GIT_CONFIG_KEY_") and value.lower() == BAR for name, value in environ.items()):
        return Failed("refused", "push_barred", "This environment carries the agent's push bar: land runs from the person's own shell.")
    return None


def _not_checked(checks: ChecksRow | None, no_change: bool) -> Failed | None:
    """Step 4: the latest checks attempt concluded `passed` (any conclusion with `--no-change`), released, not abandoned."""
    if checks is None or checks.abandoned or checks.released_at is None or checks.conclusion is None:
        return Failed("refused", "not_checked", f"The task's checks have not concluded and been released: {SHOW}")
    if checks.conclusion != "passed" and not no_change:
        return Failed("refused", "not_checked", f"The task's checks failed ({checks.reason}): they have to pass before it "
                      "lands; run them again (`tl step start`) or give the task up.")
    return None


def _task(ports: LandPorts, request: LandRequest) -> _Task | Failed:
    """Steps 2-4, then the latest candidate (step 5): reads only."""
    con = open_store(ports.lands.connect)  # the current schema, else `unavailable store`
    row = con.execute(CURRENT, (request.backlog, request.task_id)).fetchone()
    key = None if row is None else AttemptKey(str(row[0]), str(row[1]), int(row[2]))
    found = None if key is None else task_of(con, key)
    if row is None or key is None or found is None or not row[3] or following(str(row[4])) != CHECK:
        return Failed("refused", "not_done", "The task's current attempt is not a done implement attempt.")
    checks = latest(ports.work.store, key.attempt_id)
    refused = _not_checked(checks, request.no_change or request.mode == "summary")  # the summary reports any conclusion
    if refused is not None or checks is None:
        return refused or Failed("refused", "not_checked")
    candidate = ports.lands.latest(checks.key.attempt_id)
    if candidate is not None and candidate.superseded == "abandoned":  # only `tl step release --abandon` marks it so
        return Failed("refused", "abandoning", "The task's abandon stopped after its land candidate: rerun `tl step release "
                      "--abandon` to finish it. Nothing was landed.")
    return _Task(key, checks, candidate)


def _branch(origin: Origin, task: _Task, task_tip: str | None) -> Failed | None:
    """Step 7: X readable, and both task branches exactly X (land lands exactly what was checked)."""
    x, task_id = task.checks.commit, task.checks.task_id
    if origin.repo.tree(f"{x}^{{commit}}") is None:
        return Failed("refused", "commit_missing", f"The checked commit {x} is not in the repository.")
    tips = {entry.name: entry.sha for entry in origin.repo.refs([HEADS, REMOTES])}
    local = tips.get(f"{HEADS}/{task_id}") or tips.get(f"{REMOTES}/{task_id}")
    if local == x and task_tip == x:
        return None
    return Failed("refused", "branch_moved", f"task/{task_id} (local {local}, origin {task_tip}) is not the checked {x}: abandon "
                  "and restart, or reset the branch.")


def _origin(ports: LandPorts, request: LandRequest, task: _Task) -> Origin | Failed:
    """Step 6: the checkout is the attempt's repository."""
    checked = checkout_repo(ports.remotes, request.checkout)
    if isinstance(checked, AdmitRefused):
        return Failed("refused", "checkout", checked.detail)
    if isinstance(checked, AdmitUnavailable):
        return Failed("unavailable", checked.what, checked.detail)
    repo, repo_id = checked
    if repo_id != task.checks.repo_id:
        return Failed("refused", "checkout", "The checkout is not the repository of the task's implement attempt.")
    origin = Origin(repo, request.checkout.expanduser().resolve())
    try:
        return _remote(origin, request, task) or origin
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not read the checkout ({type(error).__name__}): rerun.")


def _remote(origin: Origin, request: LandRequest, task: _Task) -> Failed | None:
    """Steps 6-7: `origin` exists (its URLs as the person configured them); origin has `main`; the branch rule, except
    with `--no-change` (whatever the branch holds) and `--withdraw` (it pushes nothing: a moved branch must not block
    giving the candidate up)."""
    try:
        origin.repo.remote_url(REMOTE)  # a presence check only: the URL is never kept, logged or printed
    except MissingRemote:
        return Failed("refused", "no_remote", "The checkout has no `origin` remote: nothing was fetched or pushed.")
    try:
        main, task_tip = remote_tips(origin.repo, f"refs/heads/task/{task.checks.task_id}")
    except GitUnavailable as error:
        return Failed("unavailable", "remote", f"`origin` could not be read ({type(error).__name__}): rerun.")
    if main is None:
        return Failed("refused", "target", "`origin` has no branch `main` to land on.")
    return None if request.no_change or request.mode == "withdraw" else _branch(origin, task, task_tip)


def _read(ports: LandPorts, checks: ChecksRow) -> TaskInspection | Failed:
    """The one tracker read (`bd show`): the task's status, assignee and title."""
    read = read_task(ports.tasks, checks.task_id, checks.backlog, checks.tracker_root)
    if isinstance(read, (AdmitRefused, AdmitUnavailable)):
        kind = "refused" if isinstance(read, AdmitRefused) else "unavailable"
        return Failed(kind, "task" if isinstance(read, AdmitRefused) else "tracker", read.detail)
    return read


def _tracker(ports: LandPorts, origin: Origin, task: _Task, release: str | None) -> TaskInspection | Landed | Failed:
    """Step 8: one tracker read; closed with a pushable candidate reads origin first (delivered is recorded)."""
    checks = task.checks
    read = _read(ports, checks)
    if isinstance(read, Failed):
        return read
    if read.status == "closed":
        found = None if task.candidate is None or not task.candidate.pushable else observed(
            ports.lands, ports.work.clock, origin, task.candidate)
        if isinstance(found, (Delivered, Failed)):
            return Landed(found.row, "already_pushed", release) if isinstance(found, Delivered) else found
        return Failed("refused", "closed", f"{checks.task_id} is closed in the tracker without a land.")
    if read.status != "in_progress" or read.assignee != ACTOR:
        return Failed("refused", "claim_lost", f"The tracker shows {checks.task_id} {read.status or 'without status'}, assigned "
                      f"to {read.assignee or 'nobody'}.")
    return read


def _made(ports: LandPorts, request: LandRequest, task: _Task, origin: Origin, number: int) -> LandRow | Failed:
    """Section 5: a new candidate S onto origin's `main` as fetched now, inserted (and validated when it must be)."""
    target = fetched_target(ports.profiles, origin)
    if isinstance(target, Failed):
        return target
    o, required = target
    squashed = squashed_onto(origin, task.checks, task.title, o)
    if isinstance(squashed, Failed):
        return squashed
    s, tree_s, tree_x, tree_o = squashed
    no_change = tree_s == tree_o
    if no_change != request.no_change:
        return Failed("refused", "no_change", f"origin's main at {o} already holds X's changes, so there is nothing to push: "
                      "a person confirms that and records the task as landed (`tl step land --no-change`).") if no_change else Failed(
            "refused", "changes", "There is something to land: drop --no-change.")
    refused = None if no_change else gated(ports.profiles, origin, request.accept, o, s)
    if refused is not None:
        return refused
    same, names = tree_s == tree_x, {name for name, _ in required} != {name for name, _ in task.checks.required}
    settled = "no_change" if no_change else "same_tree" if same and not names else None
    deadline = _deadline(ports, request.minutes, settled is None)
    if isinstance(deadline, Failed):
        return deadline
    row = inserted(ports, origin.repo, task.checks, (number, o, s, same, required), settled, deadline)
    return row if isinstance(row, Failed) or row.validation is not None else _checked(ports, row)


def _deadline(ports: LandPorts, minutes: int | None, validates: bool) -> float | Failed:
    """The validation's deadline from `minutes`; refused when a block runs and there are none (0.0 when none can run)."""
    if minutes is None:
        return NEEDS_MINUTES if validates else 0.0
    return deadline_after(minutes, ports.work.clock)


def _checked(ports: LandPorts, row: LandRow) -> LandRow | Failed:
    """The validation of a pending candidate; passed is pushable, failed is `checks_failed`."""
    found = validated(ports, row)
    if isinstance(found, Failed) or found.validation == "passed":
        return found
    return Failed("refused", "checks_failed", f"The checks of S ({found.commit}) failed ({found.reason}), though they passed on "
                  "the task's own commit: the change does not hold on the current main. The `Land check:` logs say which. Nothing was "
                  "pushed; a flaky check may be retried (`tl step land`), otherwise the task starts again.")


def _no_change(ports: LandPorts, origin: Origin, current: LandRow | None, again: Callable[[], LandRow | Failed],
               release: str | None) -> LandResult:
    """`--no-change` never validates or pushes: a pending candidate is `landing`; a pushable one is read by the rule
    without a push (on origin: delivered; origin still at its O: `changes`, S is what to land; moved past it:
    superseded `moved`); then the no-change candidate (`changes` when S's tree is not O's)."""
    if current is not None and current.pending:
        return Failed("refused", "landing", "A land candidate of the task is being validated: rerun `tl step land` without "
                      "--no-change, or abandon. Nothing was recorded.")
    if current is not None and current.pushable:
        seen = observed(ports.lands, ports.work.clock, origin, current)
        if isinstance(seen, (Delivered, Failed)):
            return Landed(seen.row, "already_pushed", release) if isinstance(seen, Delivered) else seen
        if seen == "at_origin":
            return Failed("refused", "changes", f"The validated candidate S ({current.commit}) onto origin's main is still "
                          "to land: drop --no-change. Nothing was pushed.")
        ports.lands.supersede(current.key, "moved", ports.work.clock())
    made = again()
    return made if isinstance(made, Failed) else Landed(made, "no_change", release)


def _landed(found: Delivered | Failed, release: str | None) -> Landed | Failed:
    return found if isinstance(found, Failed) else Landed(found.row, found.how, release)


def _pending(ports: LandPorts, minutes: int | None, current: LandRow, origin: Origin, release: str | None,
             again: Callable[[], LandRow | Failed]) -> LandResult:
    """A pending candidate: its deadline renewed (`--minutes` needed), its validation resumed, then its delivery."""
    deadline = _deadline(ports, minutes, True)
    if isinstance(deadline, Failed):
        return deadline
    try:
        ports.lands.renew(current.key, deadline)
    except StoreRefused as refused:
        return Failed("unavailable", refused.reason, "The land candidate changed: rerun.")
    resumed = _checked(ports, ports.lands.row(current.key) or current)
    return resumed if isinstance(resumed, Failed) else _landed(deliver(ports.lands, ports.work.clock, origin, resumed, again), release)


def _delivered(ports: LandPorts, request: LandRequest, task: _Task, origin: Origin, release: str | None) -> LandResult:
    """Where the latest candidate leaves the land: validation resumed, delivery resumed, or a new candidate."""
    current, clock = task.candidate, ports.work.clock

    def again() -> LandRow | Failed:
        return _made(ports, request, task, origin, (0 if current is None else current.number) + 1)

    if request.no_change:
        return _no_change(ports, origin, current, again, release)
    if current is not None and current.pending:
        return _pending(ports, request.minutes, current, origin, release, again)
    if current is not None and current.pushable:
        return _landed(deliver(ports.lands, clock, origin, current, again), release)
    made = again()
    if isinstance(made, Failed) or made.delivery == "no_change":
        return made if isinstance(made, Failed) else Landed(made, "no_change", release)
    return _landed(deliver(ports.lands, clock, origin, made, None), release)


def _withdrawn(ports: LandPorts, origin: Origin, candidate: LandRow | None, release: str | None) -> LandResult:
    """`--withdraw`: the pushable candidate read against origin; delivered is `Landed`, else superseded `withdrawn`."""
    if candidate is None or not candidate.pushable:
        return Failed("refused", "not_landing", "No validated, undelivered land candidate: nothing to withdraw.")
    found = withdraw(ports.lands, ports.work.clock, origin, candidate)
    return Landed(found.row, found.how, release) if isinstance(found, Delivered) else found


def _closing(ports: LandPorts, found: LandResult) -> LandResult:
    """After the delivery: the task closed in the tracker and the close recorded (`land_close`)."""
    if not isinstance(found, Landed):
        return found
    row = closed(ports.lands, ports.close, ports.work.clock, found.row)
    return row if isinstance(row, Failed) else Landed(row, found.how, found.release)


def _resumed(ports: LandPorts, request: LandRequest, task: _Task) -> LandResult:
    """Step 5 onwards: a held slot released first; closed answers, delivered goes to the close; then steps 6-8, the mode
    and the close (`--withdraw` never writes the tracker)."""
    candidate, release = released(ports, task.candidate)
    if isinstance(candidate, Failed):
        return candidate
    task = _Task(task.implement, task.checks, candidate)
    if candidate is not None and candidate.delivery is not None:  # `--withdraw` never writes the tracker
        found = Landed(candidate, "already_landed" if candidate.close is not None else "delivered", release)
        return found if candidate.close is not None or request.mode == "withdraw" else _closing(ports, found)
    origin = _origin(ports, request, task)
    if isinstance(origin, Failed) or request.mode == "withdraw":
        return origin if isinstance(origin, Failed) else _withdrawn(ports, origin, candidate, release)
    read = _tracker(ports, origin, task, release)
    if not isinstance(read, TaskInspection):
        return _closing(ports, read)
    done = _closing(ports, _delivered(ports, request, replace(task, title=read.title), origin, release))
    return _accepted(ports, origin, done) if request.accept and isinstance(done, Landed) and done.how == "pushed" else done


def _accepted(ports: LandPorts, origin: Origin, done: Landed) -> Landed:
    """An accepted land shows what it changed in the gate: the facts, read from the delivered S against its O."""
    gate = gate_of(origin, ports.profiles(origin.checkout), done.row.origin, done.row.commit)
    return replace(done, gate=gate) if isinstance(gate, Gate) and gate.decisive else done


def _summary(ports: LandPorts, request: LandRequest, task: _Task) -> LandSummary | Failed:
    """`--summary`: steps 6-7, the title, the fetch, the profile at O and S in Git objects only; facts, no record."""
    origin = _origin(ports, request, task)
    if isinstance(origin, Failed):
        return origin
    checks, read = task.checks, _read(ports, task.checks)
    if isinstance(read, Failed):
        return read
    target = fetched_target(ports.profiles, origin)
    if isinstance(target, Failed):
        return target
    made = made_s(origin, task.checks, read.title, target[0])
    if isinstance(made, Failed):
        return made
    return summarized(origin, ports.profiles(origin.checkout), checks, ports.work.store.results(checks.key), made,
                      read.title, target)


def _landing(ports: LandPorts, request: LandRequest) -> LandResult:
    """Steps 1-4, then the rest."""
    refused = (None if request.minutes is None else minutes_refused(request.minutes)) or _barred(ports.environ)
    if refused is None and request.mode != "land" and request.no_change:
        refused = Failed("refused", "choices", f"--{request.mode} and --no-change exclude each other.")
    task = refused or _task(ports, request)
    if isinstance(task, Failed):
        return task
    return _summary(ports, request, task) if request.mode == "summary" else _resumed(ports, request, task)


def land(ports: LandPorts, request: LandRequest) -> LandResult:
    """The land, through the delivery and the close: `Landed`, `Withdrawn`, `LandSummary`, or `Failed` (refused: exit 1; unavailable:
    exit 3, a rerun is safe). A factory.db fault anywhere is `unavailable store`, nothing further changed by this call."""
    try:
        with operation(ports.lands, ActionKind.LAND, ids=ports.ids, subject=request.task_id, backlog=request.backlog,
                       checkout=str(request.checkout.expanduser().absolute())) as call:
            result = _landing(ports, request)
            call.resolved = not isinstance(result, Failed) or result.kind not in {"unavailable", "uncertain"}
            return result
    except Fenced:
        return Failed("refused", Reason.DRAINING, BLOCKED)
    except Unobservable:
        return Failed("unavailable", "observe", "The calling process cannot be observed.")
    except (sqlite3.Error, StoreUnavailable) as error:
        return Failed("unavailable", "store", f"{type(error).__name__}: rerun.")
