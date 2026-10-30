"""What `observe` sees, as plain facts (no IO, no git, no bd), and what `diff` answers with: the actions."""
from dataclasses import dataclass

from taskloop.contracts.ids import BeadId
from taskloop.contracts.reconcile import Lease, LoopFact, SlotFact
from taskloop.domain.reconcile.lost import BranchCommit


@dataclass(frozen=True)
class BeadFact:
    """One bead as bd shows it. `branch`: the local branch the engine names for it (task/<id>, or its metadata branch)."""
    id: str
    status: str
    assignee: str
    branch: str


@dataclass(frozen=True)
class Checkout:
    """A worktree of a repo as git lists it: its resolved path and the branch it has out ("" when detached)."""
    path: str
    branch: str


@dataclass(frozen=True)
class LocalBranch:
    """A local task/* or release/* branch at the oid it was seen at. `on_head`: git calls it merged into HEAD; `on_base`: every
    commit is on origin/main by patch; `last_commit`: its tip's commit time, 0 when unknown."""
    name: str
    oid: str
    on_head: bool = False
    on_base: bool = False
    last_commit: int = 0


@dataclass(frozen=True)
class RemoteBranch:
    """origin's task/<bead> of a closed bead whose landed record is on HEAD, at the oid ls-remote showed. `known`: git has that
    commit; `on_head`: it is on HEAD by patch (meaningful only when known)."""
    ref: str  # refs/heads/task/<bead>
    oid: str
    known: bool
    on_head: bool


@dataclass(frozen=True)
class Worktree:
    """A worktree directly under the build dir (`path` as listed there, `key` resolved, to match a Checkout). `dirty`: "" clean,
    else the reason; `last_used`: epoch seconds, 0 when unknown."""
    path: str
    key: str
    repo: str
    run_holds: bool
    shell_in: bool
    dirty: str
    on_base: bool
    last_used: float


@dataclass(frozen=True)
class RepoView:
    """One main checkout. `beads` is empty and `bd_down` says why when bd did not answer (task branches are then not looked at)."""
    path: str
    name: str
    checkouts: tuple[Checkout, ...] = ()
    beads: tuple[BeadFact, ...] = ()
    bd_down: str = ""
    task_branches: tuple[LocalBranch, ...] = ()
    remotes: tuple[RemoteBranch, ...] = ()
    release_branches: tuple[LocalBranch, ...] = ()
    leases: tuple[Lease, ...] = ()  # the beads held in progress; empty when bd did not answer
    slots: tuple[SlotFact, ...] = ()
    loops: tuple[LoopFact, ...] = ()  # the live loops of the repo (the loop registry)
    ready: int = 0  # beads ready to take
    last_beat: float = 0.0  # the latest beat of any loop of the repo, live or dead
    absent: float = 600.0  # seconds without a beat after which no loop is "absent"


@dataclass(frozen=True)
class Observed:
    """One look at the world: the repos, the build trees, the leases, and the clock and age policy the diff judges by."""
    now: float
    keep_days: float
    repos: tuple[RepoView, ...] = ()
    trees: tuple[Worktree, ...] = ()
    commits: tuple[BranchCommit, ...] = ()  # the bead-branch commits off the base (observe_commits), classed by diff.findings


@dataclass(frozen=True)
class DeleteBranch:
    """Delete a local branch only while it is at `oid`. `after`: keys of the worktrees the plan removes that hold it; if one stays,
    so does the branch."""
    repo: str
    repo_name: str
    name: str
    oid: str
    after: tuple[str, ...] = ()

    @property
    def line(self) -> str:
        return f"branch {self.name} ({self.repo_name})"


@dataclass(frozen=True)
class DeleteRemote:
    """Delete origin's `ref` only while it is at `oid`."""
    repo: str
    repo_name: str
    ref: str
    oid: str

    @property
    def line(self) -> str:
        return f"remote branch {self.ref.removeprefix('refs/heads/')} ({self.repo_name})"


@dataclass(frozen=True)
class RemoveTree:
    repo: str
    path: str
    key: str

    @property
    def line(self) -> str:
        return f"worktree {self.path}"


@dataclass(frozen=True)
class Keep:
    """A thing left alone, and why."""
    line: str
    why: str


@dataclass(frozen=True)
class ReleaseClaim:
    """Give a bead back whose lease ended and whose run is dead: only while it is still held by `holder` at generation `gen`."""
    repo: str
    repo_name: str
    bead: BeadId
    holder: str
    gen: int

    @property
    def line(self) -> str:
        return f"claim of {self.bead} by {self.holder} ({self.repo_name})"


@dataclass(frozen=True)
class FreeSlot:
    """Give a slot back that a dead run holds past its lease: only while its bead is still `holder`'s at `held_gen` `gen`."""
    repo: str
    repo_name: str
    bead: BeadId
    name: str
    holder: str
    gen: int

    @property
    def line(self) -> str:
        return f"slot {self.name} held by {self.holder or '?'} ({self.repo_name})"


@dataclass(frozen=True)
class NoLoop:
    """Ready beads and no loop alive: a finding for the owner, nothing to apply."""
    repo_name: str
    ready: int
    last_beat: float

    @property
    def line(self) -> str:
        return f"{self.repo_name} has {self.ready} ready bead(s) and no loop alive"


Action = DeleteBranch | DeleteRemote | RemoveTree | Keep | ReleaseClaim | FreeSlot | NoLoop
