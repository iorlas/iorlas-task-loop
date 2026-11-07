"""Pure conversions between planner entries and the durable merge queue."""
from collections.abc import Mapping, Sequence

from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_reconcile import BuildFact
from tlkernel.queue_doc import BuildRow, EntryRow, QueueDoc


def to_doc(entries: Sequence[Entry], builds: Mapping[str, BuildFact], *, in_flight: int, last_base: str) -> QueueDoc:
    """Capture entries and their branch-owned builds in queue order."""
    rows = []
    for entry in entries:
        build = builds.get(entry.branch)
        rows.append(EntryRow(
            branch=entry.branch, head=entry.head, phase=entry.phase.value,
            q=entry.q, tree=entry.tree, ref=entry.ref, reason=entry.reason,
            build=BuildRow(pid=build.pid, start_id=build.start_id,
                           lease_expires=build.lease_expires, worktree=build.worktree) if build else None,
        ))
    return QueueDoc(entries=rows, in_flight=in_flight, last_base=last_base)


def from_doc(doc: QueueDoc) -> tuple[list[Entry], dict[str, BuildFact]]:
    """Restore entries and builds, refusing an unrecognized phase."""
    entries = []
    builds = {}
    for row in doc.entries:
        entries.append(Entry(branch=row.branch, head=row.head, phase=Phase(row.phase),
                             q=row.q, tree=row.tree, ref=row.ref, reason=row.reason))
        if (build := row.build) is not None:
            builds[row.branch] = BuildFact(branch=row.branch, pid=build.pid, start_id=build.start_id,
                                          lease_expires=build.lease_expires, worktree=build.worktree)
    return entries, builds
