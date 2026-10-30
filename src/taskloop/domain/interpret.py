"""The one interpreter of a plan of effects (the close's, the land's): each effect once, by key (bead, run, kind), the applied keys
kept in the run's checkpoint.

A kill between two effects leaves the keys of the ones that ran; the next call with the same plan skips them and resumes at the first
unapplied one. A key is written after its effect returned, so an effect killed halfway runs again: every effect is safe to repeat
(a comment is deduped, a close of a closed bead is a no-op), none is ever repeated once its key is written.
"""
import contextlib
from collections.abc import Callable
from typing import Protocol

from taskloop.contracts import fence
from taskloop.domain import effects as fx


class Ledger(Protocol):
    def applied(self) -> frozenset[str]: ...

    def mark(self, key: str) -> None: ...


class MemoryLedger:
    """Keys kept in the process only: a run with no checkpoint (a landed run drops it) has nothing to resume from."""

    def __init__(self, keys: frozenset[str] = frozenset()) -> None:
        self.keys = set(keys)

    def applied(self) -> frozenset[str]:
        return frozenset(self.keys)

    def mark(self, key: str) -> None:
        self.keys.add(key)


def interpret[E: fx.Effect](bead: str, run: str, plan: list[E], ledger: Ledger, apply: Callable[[E], None]) -> list[E]:
    """Apply the effects of `plan` that no key says were applied, in order. -> the effects applied by this call."""
    done = ledger.applied()
    ran: list[E] = []
    for effect in plan:
        key = fx.key_of(bead, run, effect)
        if key in done:
            continue
        apply(effect)
        ledger.mark(key)
        ran.append(effect)
    return ran


class AppliedKeys(Protocol):
    """The checkpoint, as the ledger uses it."""

    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...


class CheckpointLedger:
    """The applied effects: kept in the process and in the checkpoint, so a restart finds them."""

    def __init__(self, checkpoints: AppliedKeys) -> None:
        self.checkpoints = checkpoints
        self.keys: set[str] = set()

    def applied(self) -> frozenset[str]:
        return frozenset(self.keys) | self.checkpoints.applied()

    def mark(self, key: str) -> None:
        self.keys.add(key)
        with contextlib.suppress(fence.Fenced):  # a run whose lease moved on keeps its keys in memory only
            self.checkpoints.mark_applied(key)
