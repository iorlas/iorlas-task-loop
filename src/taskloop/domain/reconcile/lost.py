"""The bead-branch commits no run will bring home, as facts and the one rule that classes them. Pure: no git, no bd, no clock."""
from dataclasses import dataclass
from typing import Final

UNKNOWN_STATE: Final = "?"  # bd itself failed: the bead's state cannot be told

LANDED: Final = "landed"
SUPERSEDED: Final = "superseded"
RECLAIMED: Final = "reclaimed"
PENDING: Final = "pending"
UNKNOWN: Final = "unknown"
LOST: Final = "lost"


@dataclass(frozen=True)
class BranchCommit:
    """One commit on a task/<bead> or wip/* branch that is not on the base, with what is known about it.
    `bead`: the bead the branch is named for (None on a wip/* branch); `aside`: a task/<bead>-stale-<time> branch --fresh set aside;
    `patch_on_base`: git cherry finds its patch on the base; `lands`: when the bead's land reached the base (empty: never);
    `state`: the bead's bd status, None when the tracker has no such bead, UNKNOWN_STATE when bd failed;
    `runs`: (start time, run id) of every engine run of the bead."""
    branch: str
    bead: str | None
    sha: str
    time: int
    subject: str
    base: str
    aside: bool = False
    patch_on_base: bool = False
    lands: tuple[float, ...] = ()
    state: str | None = None
    runs: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True)
class Finding:
    """A commit's class (landed, superseded, reclaimed, pending, unknown, lost) and why."""
    commit: BranchCommit
    cls: str
    why: str


def pending_class(c: BranchCommit) -> tuple[str, str]:
    """The class and why of a commit whose bead has not landed it, from the bead's state."""
    bead = c.bead or ""
    if c.state == UNKNOWN_STATE:
        return UNKNOWN, f"bd could not show {bead}: the tracker is unreachable"
    if c.state == "closed":
        return LOST, f"{bead} is closed and never landed this commit"
    if not c.state:
        return LOST, f"no bead {bead} in the tracker"
    later = [run for started, run in c.runs if started >= c.time]
    if later:
        return RECLAIMED, f"run {later[0]} took it up"
    return PENDING, f"{bead} is {c.state}: its next run continues the branch"


def classify(c: BranchCommit) -> Finding:
    """landed: its patch is on the base, or a land of its bead came after it; superseded: it is on a branch --fresh set aside;
    lost: no bead (a dead session's wip/*); otherwise by the bead's state (pending_class)."""
    if c.patch_on_base:
        return Finding(c, LANDED, f"its patch is on {c.base}")
    if c.bead and any(t >= c.time for t in c.lands):
        return Finding(c, LANDED, f"{c.bead} landed on {c.base} after it")
    if c.aside:
        return Finding(c, SUPERSEDED, f"--fresh set {c.branch} aside: {c.bead} started again on {c.base}")
    if not c.bead:
        return Finding(c, LOST, f"a dead session's work on {c.branch}: no bead, no run takes it")
    return Finding(c, *pending_class(c))
