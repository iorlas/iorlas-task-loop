"""Who holds a slot, since when and why: the marks on the slot's bead, read as typed values and written in one place."""
from taskloop.app.slots.env import SlotEnv, attempt, stamp
from taskloop.contracts.bead import Bead
from taskloop.contracts.ports import BeadPatch
from taskloop.contracts.slots import Hold

HELD_KEYS = ("held_by", "held_since", "held_why", "hold_until", "held_bead")


def hold_until(b: Bead | None) -> float:
    try:
        return float(b.metadata.get("hold_until") or 0) if b else 0.0
    except (TypeError, ValueError):
        return 0.0


def hold_of(b: Bead | None, now: float) -> Hold | None:
    """The slot's hold that has not expired, else None."""
    until = hold_until(b)
    if b is None or until <= now:
        return None
    m = b.metadata
    return Hold(by=m.get("held_by") or "?", since=m.get("held_since") or "?", why=m.get("held_why") or "", until=until)


def held_by(b: Bead) -> str:
    m = b.metadata
    return "{} since {} ({})".format(m.get("held_by") or b.assignee or "?", m.get("held_since") or "?", m.get("held_why") or "no reason")


def mark_held(env: SlotEnv, bead_id: str, why: str, until: float = 0, bead: str = "") -> None:
    """Write the marks: tl slot list and a refused run-task read them. `until`: a hold (tl slot hold), which outlives the
    bead's lease. `bead`: the bead run there (held_bead), which makes its area busy. A key not set is unset: bd reclaim frees a
    dead holder's slot bead but keeps its metadata, its bead's area with it."""
    sets = {"held_by": env.actor, "held_since": stamp(env.now()), "held_why": why}
    unset = []
    for key, value in (("hold_until", f"{until:.0f}" if until else ""), ("held_bead", bead)):
        if value:
            sets[key] = value
        else:
            unset.append(key)
    attempt(env.store.update, bead_id, BeadPatch(set_metadata=sets, unset_metadata=unset))


def clear_marks(env: SlotEnv, bead_id: str) -> None:
    attempt(env.store.update, bead_id, BeadPatch(unset_metadata=list(HELD_KEYS)))
