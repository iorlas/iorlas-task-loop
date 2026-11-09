"""Construct the real Git boundary for native command input."""

from pathlib import Path

from beads_client import Bd
from git_porcelain import RealRepo

from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo
from taskloop.task import TaskBinding, TaskInspection, TaskInspectionError, TaskScope
from taskloop.tracker import inspect_task


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
    return inspect_task(binding, Bd("taskloop", cwd=str(root)), task_id)
