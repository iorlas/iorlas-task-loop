"""The merge queue as data and one pure planner (docs/design/merge-queue.md section 3): the entries in queue order, what happened to
them, and `plan`, which says what to do next. Nothing here touches git, a process or the forge; the runner (app/land/queue_refs.py and
the stack) does the effects and feeds the results back through `apply`.

An entry is WAITING (no queue commit yet), BUILT (its queue commit Q(N) exists: Q(N-1) plus the head, as merge-tree made it), GATING (its
gate runs on Q(N)), GREEN (the gate passed), EJECTED (it could not join the queue: `reason`) or MERGED. Only the head of the queue merges,
and only when green, so the merge order is the queue order whatever order the gates finish in."""
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import final

from taskloop.contracts.wire import Rec

CONFLICT = "conflict"  # the head does not merge into the queue ahead of it


class Phase(StrEnum):
    WAITING = "waiting"
    BUILT = "built"
    GATING = "gating"
    GREEN = "green"
    EJECTED = "ejected"
    MERGED = "merged"


@final
class Entry(Rec):
    """branch, head: the PR's branch and the head that is judged. q, tree: its queue commit and that commit's tree ('' until built)."""

    branch: str
    head: str
    phase: Phase = Phase.WAITING
    q: str = ""
    tree: str = ""
    reason: str = ""


@final
@dataclass(frozen=True)
class Build:
    """Make Q(N) of `head` on `parent` (main for the first entry, the previous entry's Q after it)."""

    branch: str
    head: str
    parent: str


@final
@dataclass(frozen=True)
class Gate:
    branch: str
    q: str


@final
@dataclass(frozen=True)
class Merge:
    branch: str
    q: str
    tree: str


@final
@dataclass(frozen=True)
class Drop:
    """Remove the queue ref and the worktree of an entry that left the queue."""

    branch: str
    q: str


type Action = Build | Gate | Merge | Drop


@final
@dataclass(frozen=True)
class Built:
    branch: str
    q: str
    tree: str


@final
@dataclass(frozen=True)
class Ejected:
    branch: str
    reason: str


@final
@dataclass(frozen=True)
class Gated:
    branch: str
    green: bool


@final
@dataclass(frozen=True)
class Landed:
    branch: str


type Event = Built | Ejected | Gated | Landed


def live(entries: Sequence[Entry]) -> list[Entry]:
    """The entries still in the queue, in order."""
    return [e for e in entries if e.phase not in (Phase.EJECTED, Phase.MERGED)]


def plan(entries: Sequence[Entry], main: str, in_flight: int) -> list[Action]:
    """What to do now: drop the refs of entries that left, merge the head when green, gate built entries up to `in_flight` at once, and
    build the next entries on their predecessor's Q (one chain, in order, no further than `in_flight` entries past the head)."""
    acts: list[Action] = [Drop(e.branch, e.q) for e in entries if e.phase in (Phase.EJECTED, Phase.MERGED) and e.q]
    queue = live(entries)
    if queue and queue[0].phase is Phase.GREEN:
        acts.append(Merge(queue[0].branch, queue[0].q, queue[0].tree))
    gating = sum(e.phase is Phase.GATING for e in queue)
    for e in queue[: max(1, in_flight)]:
        if e.phase is Phase.BUILT and gating < in_flight:
            acts.append(Gate(e.branch, e.q))
            gating += 1
    parent = main
    for i, e in enumerate(queue[: max(1, in_flight)]):
        if e.phase is Phase.WAITING:
            acts.append(Build(e.branch, e.head, parent))
            break  # the next one needs this one's Q
        parent = e.q
        if i + 1 >= in_flight:
            break
    return acts


def apply(entries: Sequence[Entry], event: Event) -> list[Entry]:
    """The entries after `event`."""
    out = []
    for e in entries:
        if e.branch != event.branch:
            out.append(e)
        elif isinstance(event, Built):
            out.append(e.replace(phase=Phase.BUILT, q=event.q, tree=event.tree))
        elif isinstance(event, Ejected):
            out.append(e.replace(phase=Phase.EJECTED, reason=event.reason))
        elif isinstance(event, Gated):
            out.append(e.replace(phase=Phase.GREEN if event.green else Phase.EJECTED, reason="" if event.green else "gate"))
        else:
            out.append(e.replace(phase=Phase.MERGED))
    return out
