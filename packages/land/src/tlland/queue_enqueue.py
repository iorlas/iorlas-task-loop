"""Dependency and touched-path checks before queue refs are built."""
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Protocol

from tlkernel.beadsport import Beads
from tlkernel.gitport import Git
from tlkernel.ids import BeadId

from tlland.cmds import Cmds, Stop
from tlland.domain.queue_deps import Gate, State, find_cycle, gate
from tlland.domain.queue_overlap import waits_for
from tlland.treecheck import TreeGuard


class Host(Protocol):
    """Ports needed to decide admission and gate concurrency."""

    beads: Beads
    git: Git
    cmds: Cmds
    trees: TreeGuard
    repo: str
    jobs: int


def dependencies(host: Host, beads: Sequence[str]) -> tuple[dict[str, list[str]], dict[str, State]]:
    """Read at most 64 distinct beads breadth first, retaining all discovered edges."""
    pending = deque(beads)
    edges: dict[str, list[str]] = {}
    states: dict[str, State] = {}
    while pending and len(edges) < 64:
        bead = pending.popleft()
        if bead in edges:
            continue
        record = host.beads.show(BeadId(bead))
        parents = [dep for dep in record.dependencies if dep.type == "blocks"] if record else []
        edges[bead] = [dep.id for dep in parents]
        for dep in parents:
            if dep.status == "closed":
                states[dep.id] = State.MERGED
            else:
                states.setdefault(dep.id, State.OPEN)
            if dep.id not in edges:
                pending.append(dep.id)
    return edges, states


def enqueue(host: Host, heads: Sequence[tuple[str, str]], beads_of: Mapping[str, str]) -> int:
    """Refuse blocked dependencies and serialize overlapping paths.

    Abandonment needs bd timestamps and is not derived here. Earlier run items
    count as merged because the queue delivers them in order.
    """
    beads = [beads_of.get(branch, "") for branch, _oid in heads]
    edges, closed = dependencies(host, [bead for bead in beads if bead])
    earlier: set[str] = set()
    for bead in beads:
        if not bead:
            continue
        states = {**closed, **dict.fromkeys(earlier, State.MERGED)}
        result = gate(bead, edges, states)
        if result is Gate.BLOCKED_CYCLE:
            raise Stop(1, "queue: dependency cycle " + " -> ".join(find_cycle(edges)))
        if result in (Gate.WAITING, Gate.BLOCKED_ABANDONED):
            parent = next(p for p in edges[bead] if states.get(p) is not State.MERGED)
            why = "abandoned" if result is Gate.BLOCKED_ABANDONED else "not merged to main"
            raise Stop(1, f"queue: {bead} waits for {parent} ({why})")
        earlier.add(bead)
    touched = {
        branch: [entry.path for entry in host.git.diff_entries(
            host.repo, host.git.merge_base(host.repo, host.trees.main_ref, oid), oid,
        )]
        for branch, oid in heads
    }
    waits = waits_for([branch for branch, _oid in heads], touched)
    for branch, parent in waits.items():
        host.cmds.log.note(f"{branch} waits for {parent}: touched paths overlap")
    return 1 if waits else host.jobs
