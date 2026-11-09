"""Construct the real Git, tracker and store boundaries for native command input."""

import time
from pathlib import Path

from any_agent import run
from beads_client import Bd, Runner
from git_porcelain import RealRepo
from sqlite_store import Store

from taskloop.plan import Credentials, PlanAttempts
from taskloop.plan_admit import Claim, PlanAdmission, Unclaim
from taskloop.plan_files import PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo
from taskloop.slots import Adopted, NotAdopted, adopt
from taskloop.task import TaskBinding, TaskInspection, TaskInspectionError, TaskScope
from taskloop.tracker import inspect_task

ACTOR = "taskloop"


def inspect_checkout(path: str) -> RepoInspection:
    """Resolve the native path once and request fresh shared-library observations."""
    try:
        expanded = Path(path).expanduser()
    except RuntimeError as error:
        raise UnsupportedCheckout(f"Cannot expand checkout path: {path}") from error
    checkout = expanded.resolve()
    return inspect_repo(RealRepo(checkout, memoize=False), checkout)


def inspect_tracker_task(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    """Bind the supplied logical backlog to the explicit tracker root, without discovery."""
    scope = TaskScope(backlog)
    if not tracker_root.strip():
        raise TaskInspectionError("invalid_binding", "An explicit nonempty tracker root is required")
    try:
        root = Path(tracker_root).expanduser().resolve()
        if not root.is_dir():
            raise TaskInspectionError("invalid_binding", f"Tracker root is not an available directory: {root}")
    except (RuntimeError, OSError) as error:
        raise TaskInspectionError("invalid_binding", f"Cannot resolve tracker root: {tracker_root}") from error
    binding = TaskBinding(scope, root)
    return inspect_task(binding, Bd(ACTOR, cwd=str(root)), task_id)


def open_plan_attempts(database: Path, artifacts: Path, credentials: Credentials) -> PlanAttempts:
    """Real wiring: released run, per-thread shared writers on factory.db, wall-clock deadlines."""
    store = Store(SCHEMA)
    return PlanAttempts(
        PlanStore(lambda: store.shared_rw(database), store.begin_immediate), PlanFiles(artifacts), credentials, run, time.time
    )


def adopt_slots(database: Path, checkout: Path, root: Path, count: int) -> tuple[Adopted | NotAdopted, ...]:
    """Adopt worktrees a person already made with `git worktree add --detach <root>/<repo_id>/sN`; creates none."""
    store = Store(SCHEMA)
    try:
        repo = RealRepo(checkout.expanduser().resolve(), memoize=False)
        return adopt(lambda: store.shared_rw(database), store.begin_immediate, repo, root, count)
    finally:
        store.close_shared()


def tracker_claims(run: Runner | None = None) -> tuple[Claim, Unclaim]:
    """`Bd.claim` and the compensating `Bd.unclaim` fenced to this actor (never forced), bound per tracker root."""

    def bd(tracker_root: str) -> Bd:
        return Bd(ACTOR, cwd=str(Path(tracker_root).expanduser().resolve()), run=run)

    def claim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).claim(task_id)

    def unclaim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).unclaim(task_id, if_assignee=ACTOR)

    return claim, unclaim


def open_plan_admission(database: Path, artifacts: Path) -> PlanAdmission:
    """Real wiring: per-thread shared writers on factory.db, the tracker claim, the real Git boundary, wall-clock deadlines."""
    store = Store(SCHEMA)
    claim, unclaim = tracker_claims()
    return PlanAdmission(
        lambda: store.shared_rw(database),
        store.begin_immediate,
        PlanFiles(artifacts),
        inspect_tracker_task,
        lambda checkout: RealRepo(checkout, memoize=False),
        claim,
        unclaim,
        time.time,
    )
