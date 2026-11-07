"""Observe and clean an interrupted queue without starting builds or merging PRs."""
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel.gitport import Git
from tlkernel.queue_doc import QueueDoc

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.queue_refs import PREFIX, QueueRefs
from taskloop.app.land.treecheck import Tested, TreeGuard
from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_persist import from_doc
from taskloop.domain.land.queue_reconcile import (
    Action,
    AssertAndRecord,
    DropRef,
    Facts,
    KillBuild,
    NotifyEjected,
    PrFact,
    RemoveWorktree,
    ResetPending,
    reconcile,
)
from taskloop.stores.runlog import RunLog


class Host(Protocol):
    """Recovery ports; the caller owns persistence and no process survives as ours."""

    git: Git
    cmds: Cmds
    forge: Forge
    trees: TreeGuard
    repo: str
    record: Callable[[str, str], int]
    log: RunLog


def facts(host: Host, doc_entries: QueueDoc, now: Callable[[], float]) -> Facts:
    """A restart owns no build: stored PIDs are never probed or signalled."""
    entries, builds = from_doc(doc_entries)
    prs = {}
    for entry in entries:
        pr = host.forge.find(entry.branch, entry.head)
        if pr is not None:
            pr = host.forge.view(pr.number)
            prs[entry.branch] = PrFact(pr.state.lower(), pr.merge_sha)
    return Facts(
        refs=frozenset(ref.name for ref in host.git.for_each_ref(host.repo, PREFIX)),
        worktrees=frozenset(tree.path for tree in host.git.checkouts(host.repo)
                            if Path(tree.path).name.startswith("tl-land-gate-")),
        alive={}, main_sha=host.git.rev_parse(host.repo, host.trees.main_ref),
        prs=prs, builds=builds,
        recorded=frozenset(e.branch for e in entries if e.phase is Phase.MERGED),
        notified=frozenset(), now=now(),
    )


class Recover:
    def __init__(self, host: Host) -> None:
        self.host = host

    def record(self, action: AssertAndRecord, entries: Sequence[Entry]) -> None:
        host = self.host
        entry = next(e for e in entries if e.branch == action.branch)
        pr = host.forge.find(entry.branch, entry.head)
        if pr is None:
            raise Stop(1, f"queue: PR disappeared for {entry.branch}")
        bead = entry.branch.removeprefix("task/") if entry.branch.startswith("task/") else ""
        host.trees.verify(Tested(parent="", parent_tree="", tree=entry.tree),
                          host.git.rev_parse(host.repo, action.merge_sha + "^"), action.merge_sha, pr.number, bead)
        if bead:
            rc = host.record(bead, action.merge_sha)
            if rc:
                raise Stop(rc, f"queue: recording {bead} was refused (exit {rc})")
        else:
            host.log.note(f"queue: {entry.branch} has no bead; no land recorded")

    def apply(self, action: Action, entries: Sequence[Entry]) -> None:
        host = self.host
        if isinstance(action, KillBuild):
            host.log.note(f"queue: build {action.pid} is not owned after restart; no signal sent")
        elif isinstance(action, RemoveWorktree):
            host.git.remove_worktree_force(host.repo, action.path)
        elif isinstance(action, DropRef):
            QueueRefs(host.cmds, host.repo).drop(action.ref)
        elif isinstance(action, ResetPending):
            pass  # The new run replaces the document.
        elif isinstance(action, AssertAndRecord):
            self.record(action, entries)
        elif isinstance(action, NotifyEjected):
            host.log.note(f"queue: {action.branch} was ejected")


def recover(host: Host, doc: QueueDoc, now: float) -> list[Action]:
    """Apply reconciliation effects, retaining the document for the caller."""
    entries, _builds = from_doc(doc)
    actions = reconcile(entries, facts(host, doc, lambda: now))
    runner = Recover(host)
    for action in actions:
        runner.apply(action, entries)
    return actions
