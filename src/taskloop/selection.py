"""Which ready, approved tasks a scheduling round may admit, and in which order: pure, no IO in the comparator.

Eligibility, in order: any attempt of the task in factory.db (`attempted`, or `abandoned` when its current attempt was
abandoned); assigned to another actor than the factory (`assigned`); a missing or cyclic ancestor chain (`ancestry`), or
one whose ancestor could not be read (`unavailable:ancestry`, transient). Order (the owner-accepted hierarchical-priority
contract, tl-8bh9.3): own priority (P2 when missing), then ancestor priorities nearest parent first, padded with P2 to the
deepest candidate's depth, then the natural task id (digit runs compared as numbers). The tracker's readiness and
approval are its own facts, never recomputed here.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Final, Literal

from taskloop.task import TaskInspectionError
from taskloop.tracker import TaskRow

type Skip = Literal["attempted", "abandoned", "assigned", "ancestry", "unavailable:ancestry"]
type Lookup = Callable[[str], TaskRow | None]  # None: the tracker says no such task; a failed read raises TaskInspectionError
DEFAULT: Final = 2
DIGITS: Final = re.compile(r"(\d+)")


def natural(task_id: str) -> tuple[tuple[int, int | str], ...]:
    """`t-2` before `t-10`: digit runs as numbers, the rest as text (tagged so the two never compare)."""
    return tuple((1, int(part)) if part.isdecimal() else (0, part) for part in DIGITS.split(task_id) if part)


def chain(row: TaskRow, lookup: Lookup) -> tuple[int, ...] | Skip:
    """The ancestor priorities, nearest parent first (P2 for a missing priority); `ancestry` for a missing ancestor or a
    cycle, `unavailable:ancestry` when an ancestor could not be read (transient: the next round reads it again)."""
    priorities: list[int] = []
    seen = {row.task_id}
    parent = row.parent
    while parent:
        if parent in seen:
            return "ancestry"
        seen.add(parent)
        try:
            found = lookup(parent)
        except TaskInspectionError:
            return "unavailable:ancestry"
        if found is None:
            return "ancestry"
        priorities.append(DEFAULT if found.priority is None else found.priority)
        parent = found.parent
    return tuple(priorities)


def _eligible(row: TaskRow, attempts: Mapping[str, bool], actor: str) -> Skip | None:
    if row.task_id in attempts:
        return "abandoned" if attempts[row.task_id] else "attempted"
    return "assigned" if row.assignee and row.assignee != actor else None


def order(
    rows: Sequence[TaskRow], lookup: Lookup, attempts: Mapping[str, bool], actor: str
) -> tuple[tuple[TaskRow, ...], tuple[tuple[str, Skip], ...]]:
    """The eligible rows in admission order, and each skipped one with its reason (in the tracker's order). `attempts`:
    each task id with an attempt here, True when its current attempt is abandoned. Chains are read before sorting."""
    skipped: list[tuple[str, Skip]] = []
    chains: list[tuple[TaskRow, tuple[int, ...]]] = []
    for row in rows:
        found = _eligible(row, attempts, actor) or chain(row, lookup)
        if isinstance(found, tuple):
            chains.append((row, found))
        else:
            skipped.append((row.task_id, found))
    depth = max((len(found) for _row, found in chains), default=0)

    def key(entry: tuple[TaskRow, tuple[int, ...]]) -> tuple[int, tuple[int, ...], tuple[tuple[int, int | str], ...]]:
        row, found = entry
        own = DEFAULT if row.priority is None else row.priority
        return own, found + (DEFAULT,) * (depth - len(found)), natural(row.task_id)

    return tuple(row for row, _found in sorted(chains, key=key)), tuple(skipped)
