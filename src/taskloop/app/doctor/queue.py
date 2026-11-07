"""Read-only queue diagnostics: no forge reads, so AssertAndRecord never appears.

Actions are described to the owner, never executed; stores are never written.
"""
from tlkernel.check_files import repo_key
from tlkernel.gitport import Git
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.wire import Refused

from taskloop.domain.land.queue_persist import from_doc
from taskloop.domain.land.queue_reconcile import DropRef, NotifyEjected, RemoveWorktree, ResetPending, reconcile
from taskloop.domain.land.queue_world import world
from taskloop.stores.bundle import Stores


def findings(doc: QueueDoc | None, state: QueueState | None, git: Git, repo: str,
             main_ref: str, now: float) -> list[str]:
    """Describe a freeze or the recovery needed by the stored queue."""
    if state is not None and state.frozen:
        detail = ""
        if state.incidents:
            incident = max(state.incidents, key=lambda incident: incident.t)
            detail = (f" ({incident.kind}, PR #{incident.pr}, expected tree {incident.expected_tree[:12]}"
                      f" vs landed tree {incident.landed_tree[:12]})")
        return [f"queue is frozen by a tree mismatch{detail}; nothing lands until the owner clears it"]
    if doc is None:
        return []
    entries, builds = from_doc(doc)
    lines = []
    for action in reconcile(entries, world(git, repo, main_ref, entries, builds, {}, now)):
        if isinstance(action, DropRef):
            lines.append(f"orphan ref {action.ref}")
        elif isinstance(action, RemoveWorktree):
            lines.append(f"orphan worktree {action.path}")
        elif isinstance(action, ResetPending):
            lines.append(f"entry {action.branch} must be reset: build lost or queue commit gone")
        elif isinstance(action, NotifyEjected):
            lines.append(f"ejected {action.branch} not yet told")
    return lines


def report(stores: Stores, git: Git, repo: str, main_ref: str, now: float) -> list[str]:
    """Read the repo's queue documents and print each violation as a FAIL line."""
    key = repo_key(git, repo)
    try:
        document = stores.queue.of(key).need()
    except Refused as e:
        print(f"FAIL queue: {e}")
        return [str(e)]
    lines = findings(document, stores.queue_state.of(key).get(), git, repo, main_ref, now)
    for line in lines:
        print(f"FAIL queue: {line}")
    return lines
