"""Dependency gates: docs/design/merge-queue.md section 11, edge cases 1 and 2."""
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

ABANDONED_TIMEOUT_S: Final = 86400.0


class State(StrEnum):
    OPEN = "open"
    MERGED = "merged"
    ABANDONED = "abandoned"


class Gate(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    BLOCKED_ABANDONED = "blocked_abandoned"
    BLOCKED_CYCLE = "blocked_cycle"


def find_cycle(edges: Mapping[str, Sequence[str]]) -> list[str]:
    """Return a closed cycle using iterative DFS (design section 11, edge case 1)."""
    done: set[str] = set()
    for root in edges:
        if root in done:
            continue
        path = [root]
        active = {root: 0}
        stack = [iter(edges.get(root, ()))]
        while stack:
            parent = next(stack[-1], None)
            if parent is None:
                done.add(path.pop())
                active.popitem()
                stack.pop()
            elif parent in active:
                return [*path[active[parent]:], parent]
            elif parent not in done:
                active[parent] = len(path)
                path.append(parent)
                stack.append(iter(edges.get(parent, ())))
    return []


def _in_cycle(bead: str, edges: Mapping[str, Sequence[str]]) -> bool:
    pending = list(edges.get(bead, ()))
    seen: set[str] = set()
    while pending:
        parent = pending.pop()
        if parent == bead:
            return True
        if parent not in seen:
            seen.add(parent)
            pending.extend(edges.get(parent, ()))
    return False


def gate(
    bead: str,
    edges: Mapping[str, Sequence[str]],
    states: Mapping[str, State],
    *,
    abandoned_for_s: Mapping[str, float] = {},
    timeout_s: float = ABANDONED_TIMEOUT_S,
) -> Gate:
    """Reject cycles and expired abandonment (design section 11, edge cases 1 and 2).

    Only merged parents release the child; abandonment requests owner intervention.
    """
    if _in_cycle(bead, edges):
        return Gate.BLOCKED_CYCLE
    parents = edges.get(bead, ())
    if any(
        states.get(parent) is State.ABANDONED
        and abandoned_for_s.get(parent, 0.0) > timeout_s
        for parent in parents
    ):
        return Gate.BLOCKED_ABANDONED
    return Gate.READY if all(states.get(p) is State.MERGED for p in parents) else Gate.WAITING
