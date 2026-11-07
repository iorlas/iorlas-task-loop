"""Pure crash recovery for queue entries and observed build resources.

Actions describe effects for a future runner; applying and settling them models a
completed recovery without touching a store, forge, process or filesystem.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import final

from taskloop.domain.land.queue_model import Entry, Phase, live

# The app's queue_refs uses this namespace; the domain cannot import the app.
PREFIX = "refs/tl/queue/"


@final
@dataclass(frozen=True)
class BuildFact:
    """A build's process identity, lease and resource ownership."""

    branch: str
    pid: int
    start_id: str
    lease_expires: float
    worktree: str


@final
@dataclass(frozen=True)
class PrFact:
    """Forge state and the commit of a completed merge, if known."""

    state: str
    merge_sha: str = ""


@final
@dataclass(frozen=True)
class Facts:
    """One observed world, including the clock reading used for leases."""

    refs: frozenset[str]
    worktrees: frozenset[str]
    alive: Mapping[int, str]
    main_sha: str
    prs: Mapping[str, PrFact]
    builds: Mapping[str, BuildFact]
    recorded: frozenset[str]
    notified: frozenset[str]
    now: float


@final
@dataclass(frozen=True)
class KillBuild:
    """Stop an expired build that still owns its process identity."""

    branch: str
    pid: int


@final
@dataclass(frozen=True)
class RemoveWorktree:
    """Remove an unowned build directory."""

    path: str


@final
@dataclass(frozen=True)
class DropRef:
    """Remove an unowned queue ref."""

    ref: str


@final
@dataclass(frozen=True)
class ResetPending:
    """Clear the queue commit and retry an interrupted entry."""

    branch: str


@final
@dataclass(frozen=True)
class AssertAndRecord:
    """Assert the landed result and record it without merging again."""

    branch: str
    merge_sha: str


@final
@dataclass(frozen=True)
class NotifyEjected:
    """Tell the owner that their entry left the queue."""

    branch: str


type Action = KillBuild | RemoveWorktree | DropRef | ResetPending | AssertAndRecord | NotifyEjected


def _healthy(build: BuildFact, facts: Facts) -> bool:
    return facts.alive.get(build.pid) == build.start_id and build.lease_expires > facts.now


def reconcile(entries: Sequence[Entry], facts: Facts) -> list[Action]:
    """Plan recovery in effect-kind order, then lexical resource order."""
    records = {
        e.branch: pr.merge_sha for e in entries
        if (pr := facts.prs.get(e.branch)) is not None
        and pr.state == "merged" and pr.merge_sha and e.branch not in facts.recorded
    }
    queue = [e for e in live(entries) if e.branch not in records]
    resets: set[str] = set()
    kills: set[tuple[str, int]] = set()
    for e in queue:
        build = facts.builds.get(e.branch)
        if e.phase is Phase.GATING and (build is None or not _healthy(build, facts)):
            resets.add(e.branch)
            if build and build.lease_expires <= facts.now and facts.alive.get(build.pid) == build.start_id:
                kills.add((e.branch, build.pid))
        if e.phase in (Phase.BUILT, Phase.GATING, Phase.GREEN, Phase.RED) and e.ref not in facts.refs:
            resets.add(e.branch)
    killed_pids = {pid for _, pid in kills}
    resets.update(e.branch for e in queue if e.phase is Phase.GATING
                  and (build := facts.builds.get(e.branch)) is not None
                  and build.pid in killed_pids)
    retained = [e for e in queue if e.branch not in resets]
    refs = {e.ref for e in retained}
    paths = {
        build.worktree for e in retained
        if (build := facts.builds.get(e.branch)) is not None
        and _healthy(build, facts) and build.pid not in killed_pids
    }
    actions: list[Action] = [KillBuild(branch, pid) for branch, pid in sorted(kills)]
    actions.extend(RemoveWorktree(path) for path in sorted(facts.worktrees - paths))
    actions.extend(DropRef(ref) for ref in sorted(facts.refs - refs) if ref.startswith(PREFIX))
    actions.extend(ResetPending(branch) for branch in sorted(resets))
    actions.extend(AssertAndRecord(branch, sha) for branch, sha in sorted(records.items()))
    actions.extend(NotifyEjected(branch) for branch in sorted({
        e.branch for e in entries if e.phase is Phase.EJECTED and e.branch not in facts.notified
    }))
    return actions


def apply_actions(entries: Sequence[Entry], actions: Sequence[Action]) -> list[Entry]:
    """Project completed recovery effects onto queue state."""
    out = list(entries)
    for action in actions:
        if isinstance(action, ResetPending):
            out = [e.replace(phase=Phase.WAITING, q="", tree="", ref="", after="")
                   if e.branch == action.branch else e for e in out]
        elif isinstance(action, AssertAndRecord):
            out = [e.replace(phase=Phase.MERGED) if e.branch == action.branch else e for e in out]
    return out


def settle(facts: Facts, actions: Sequence[Action]) -> Facts:
    """Project successful effects onto observations, preserving the input."""
    refs, paths = set(facts.refs), set(facts.worktrees)
    alive, builds = dict(facts.alive), dict(facts.builds)
    recorded, notified = set(facts.recorded), set(facts.notified)
    for action in actions:
        if isinstance(action, KillBuild):
            alive.pop(action.pid, None)
        elif isinstance(action, RemoveWorktree):
            paths.discard(action.path)
        elif isinstance(action, DropRef):
            refs.discard(action.ref)
        elif isinstance(action, ResetPending):
            builds.pop(action.branch, None)
        elif isinstance(action, AssertAndRecord):
            recorded.add(action.branch)
        elif isinstance(action, NotifyEjected):
            notified.add(action.branch)
    return replace(facts, refs=frozenset(refs), worktrees=frozenset(paths), alive=alive,
                   builds=builds, recorded=frozenset(recorded), notified=frozenset(notified))
