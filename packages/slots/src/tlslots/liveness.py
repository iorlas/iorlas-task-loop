"""The slot liveness invariants (tl-bxk.10.33.12, docs/design/slot-grant.md (b)): a pure function over what the slots, the waiters
and the clock show. The 2026-11-03 stall was a slot nobody could take beside seven live waiters for two hours, and nothing said so.
Times are epoch seconds; a time the caller cannot read is None and never makes a violation (the caller says it could not look)."""
from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    FREE_BESIDE_WAITER = "free_beside_waiter"  # a slot anyone could take and a live waiter, for longer than a waiter's poll
    READY_IDLE_FREE = "ready_idle_free"        # a ready bead, an idle loop and a free slot, together for too long
    ASIDE_TOO_LONG = "aside_too_long"          # a slot out of use for failing setup, for too long
    ORPHAN_HELD = "orphan_held"                # a slot an automatic taker holds with no live engine lock on its worktree


@dataclass(frozen=True)
class Limits:
    grant_s: float = 120.0    # waiters poll at most every 30 s
    idle_s: float = 600.0
    aside_s: float = 1800.0
    orphan_s: float = 900.0   # a taker writes its lock right after the take; a slot setup may precede it


LIMITS = Limits()


@dataclass(frozen=True)
class SlotFact:
    name: str
    free_since: float | None = None   # grantable now (nothing holds, sets aside or excludes it) since then
    aside_since: float | None = None  # excluded until a setup probe passes, since then
    held_since: float | None = None   # held by the loop or a run-task (not a person's hold or take), since then
    locked: bool = False              # a live engine lock names its worktree


@dataclass(frozen=True)
class Waiter:
    seq: int
    since: float
    live: bool = True


@dataclass(frozen=True)
class Violation:
    kind: Kind
    slot: str
    since: float
    why: str


def violations(slots: list[SlotFact], waiters: list[Waiter], now: float, *, ready_since: float | None = None, idle_loops: int = 0,
               limits: Limits = LIMITS) -> list[Violation]:
    """Every invariant that does not hold at `now`. `ready_since`: when the oldest ready bead began to wait (None: none does);
    `idle_loops`: loops that run no bead and wait in no line."""
    out: list[Violation] = []
    live = sorted((w for w in waiters if w.live), key=lambda w: w.since)
    for s in slots:
        if s.free_since is not None:
            if live:
                began = max(s.free_since, live[0].since)
                if now - began > limits.grant_s:
                    out.append(Violation(Kind.FREE_BESIDE_WAITER, s.name, began, f"slot {s.name} is free and {len(live)} waiter(s) are "
                                         f"in line (first: #{live[0].seq}) for {now - began:.0f} s"))
            if ready_since is not None and idle_loops > 0 and now - max(s.free_since, ready_since) > limits.idle_s:
                began = max(s.free_since, ready_since)
                out.append(Violation(Kind.READY_IDLE_FREE, s.name, began,
                                     f"a bead is ready, {idle_loops} loop(s) are idle and slot {s.name} is free for {now - began:.0f} s"))
        if s.aside_since is not None and now - s.aside_since > limits.aside_s:
            out.append(Violation(Kind.ASIDE_TOO_LONG, s.name, s.aside_since,
                                 f"slot {s.name} has been set aside for {now - s.aside_since:.0f} s: its setup probe never passes"))
        if s.held_since is not None and not s.locked and now - s.held_since > limits.orphan_s:
            out.append(Violation(Kind.ORPHAN_HELD, s.name, s.held_since,
                                 f"slot {s.name} is held for {now - s.held_since:.0f} s and no live engine lock is on its worktree"))
    return out
