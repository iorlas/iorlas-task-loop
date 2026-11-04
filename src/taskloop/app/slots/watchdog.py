"""The slot liveness watchdog (tl-bxk.10.33.12): reads the slots, the line and the engine locks, asks domain/slot_liveness what does not
hold, logs each violation as a `slot_stall` event (once per episode) and heals the ones that can be healed. A waiter runs it every
poll (line.wait_slot), the loop once a pass, `tl doctor` read-only (`look`). It never fails its caller: a bd or disk error is a look
that did not happen."""
import time
from dataclasses import dataclass, field
from datetime import datetime

from taskloop.app.slots.env import SlotEnv, attempt
from taskloop.app.slots.marks import hold_of
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts.bead import Bead
from taskloop.contracts.locks import Ticket
from taskloop.contracts.ports import BdFailure, BeadPatch
from taskloop.contracts.slots import SlotFail
from taskloop.domain.slot_liveness import LIMITS, Kind, Limits, SlotFact, Violation, Waiter, violations

EVERY = 30.0       # seconds between two looks by one caller
RELOG = 1800.0     # an episode that goes on is logged again after this
AUTO_TAKERS = ("tl loop", "run-task")  # a person's hold or take has no engine lock and is no violation


@dataclass
class Watch:
    """What one caller remembers between its ticks: when it last looked and when it logged each violation (one row per episode)."""

    looked: float | None = None
    logged: dict[tuple[str, str], float] = field(default_factory=dict)  # (invariant, slot) -> when


def _epoch(text: str, iso: bool) -> float | None:
    try:
        if iso:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return time.mktime(time.strptime(text, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _held_since(b: Bead) -> float | None:
    m = b.metadata
    why = str(m.get("held_why") or "")
    return _epoch(str(m.get("held_since") or ""), False) if why.startswith(AUTO_TAKERS) else None


def facts(env: SlotEnv, now: float, *, stamp: bool = False) -> tuple[list[SlotFact], list[Waiter]]:
    """The slots and the line as the invariants read them. `stamp`: write aside_since on a slot first seen set aside (only a tick does)."""
    pool, out = SlotPool(env), list[SlotFact]()
    for slot in pool.slots():
        b = slot.bead
        if b is None or not pool.configured(slot.name):
            continue
        pending = b.metadata.get("aside_probe") == "pending"
        locked = bool(env.busy(slot.dir))
        since = _epoch(b.updated_at, True) if b.updated_at else None
        aside: float | None = None
        if pending:
            seen = b.metadata.get("aside_since")
            aside = float(seen) if seen else now
            if stamp and not seen:
                attempt(env.store.update, b.id, BeadPatch(set_metadata={"aside_since": f"{now:.0f}"}))
        elif stamp and b.metadata.get("aside_since"):
            attempt(env.store.update, b.id, BeadPatch(unset_metadata=["aside_since"]))
        free = not pending and not slot.free_reason()
        held = b.status != "open" and hold_of(b, now) is None
        out.append(SlotFact(slot.name, free_since=since if free else None, aside_since=aside,
                            held_since=_held_since(b) if held else None, locked=locked))
    return out, [Waiter(t.seq, t.since) for t in env.tickets.line(env.repo_key)]


def heal(env: SlotEnv, v: Violation, own: Ticket | None = None) -> bool:
    """True when the cause was removed. A free slot beside waiters that do not take it: the tickets ahead of the caller's own `own`
    (the caller polls, so it is the proof the line is stuck there), else the first one, go; a waiter needs no ticket to take, so a live
    one still can, and one hung in a call, which held the whole line, cannot. An automatic holder with no engine lock: its lease is
    dropped. A slot set aside, or a ready bead nobody picks, only says so."""
    pool = SlotPool(env)
    try:
        if v.kind is Kind.FREE_BESIDE_WAITER:
            with env.take_lock():
                pool.free_expired()
            line = env.tickets.line(env.repo_key)
            for t in [x for x in line if own is not None and (x.prio, x.seq) < (own.prio, own.seq)] or line[:1]:
                env.tickets.drop(env.repo_key, t.seq)
            return True
        if v.kind is Kind.ORPHAN_HELD:
            slot = pool.slot(v.slot)
            if not env.busy(slot.dir):
                return slot.release(force=True)
    except (BdFailure, OSError, SlotFail):
        return False
    return False


def look(env: SlotEnv, *, ready_since: float | None = None, idle_lanes: int = 0, limits: Limits = LIMITS) -> list[Violation]:
    """The violations now; nothing is written."""
    now = env.now()
    try:
        slots, waiters = facts(env, now)
    except (BdFailure, OSError):
        return []
    return violations(slots, waiters, now, ready_since=ready_since, idle_lanes=idle_lanes, limits=limits)


def tick(env: SlotEnv, watch: Watch, *, ready_since: float | None = None, idle_lanes: int = 0, limits: Limits = LIMITS,
         own: Ticket | None = None) -> list[Violation]:
    """Look (at most every EVERY s per `watch`), log each new violation as an event and heal it; -> the violations found."""
    now = env.now()
    if watch.looked is not None and now - watch.looked < EVERY:
        return []
    watch.looked = now
    try:
        slots, waiters = facts(env, now, stamp=True)
    except (BdFailure, OSError):
        return []
    found = violations(slots, waiters, now, ready_since=ready_since, idle_lanes=idle_lanes, limits=limits)
    for v in found:
        healed = heal(env, v, own)
        key = (v.kind.value, v.slot)
        if key not in watch.logged or now - watch.logged[key] >= RELOG:
            watch.logged[key] = now
            env.event("slot_stall", "", slot=v.slot, invariant=v.kind.value, why=v.why, since=v.since, healed=healed, repo=env.repo)
    return found


def lines(violations_: list[Violation]) -> list[str]:
    return [f"slot stall ({v.kind.value}): {v.why}" for v in violations_]
