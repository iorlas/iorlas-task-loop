"""A failed reset excludes a slot until a real reset and setup probe passes. The probes are spaced out: the first one 30 minutes after
the slot was set aside, then 60 and 120 minutes after each failed one (120 repeats), so a broken slot costs one probe per interval and
a mended one is back within two hours. The bead's metadata keeps `aside_level` (failed probes so far) and `aside_until` (epoch)."""
import contextlib

from tlkernel.beadsport import BdFailure, BeadPatch
from tlkernel.slots import SlotFail, SlotGitError

from taskloop.app.slots.reset import setup
from taskloop.app.slots.surface import SlotView

STEPS_S = (1800.0, 3600.0, 7200.0)


def _wait(level: int) -> str:
    return f"{STEPS_S[min(level, len(STEPS_S) - 1)]:.0f}"


def mark(slot: SlotView) -> None:
    """The slot was just set aside: its first probe is due in 30 minutes."""
    env = slot.env
    with contextlib.suppress(BdFailure):
        env.store.update(slot.slot_bead().id, BeadPatch(set_metadata={
            "aside_level": "0", "aside_until": f"{env.now() + float(_wait(0)):.0f}"}))


def due(slot: SlotView) -> bool:
    """False while the interval since the set-aside or the last failed probe has not passed."""
    until = slot.slot_bead().metadata.get("aside_until")
    return not until or slot.env.now() >= float(until)


def check(slot: SlotView) -> bool:
    """Probe a claimed slot, including setup even when its inputs have not changed. False without a probe while it is not due."""
    env, bead = slot.env, slot.slot_bead()
    if not due(slot):
        return False
    try:
        slot.ready_for("")
        setup(slot, force=True)
    except (SlotFail, SlotGitError, BdFailure, OSError) as error:
        level = int(bead.metadata.get("aside_level") or 0) + 1
        env.store.update(bead.id, BeadPatch(set_metadata={
            "aside_probe": "pending", "aside_level": str(level), "aside_until": f"{env.now() + float(_wait(level)):.0f}"}))
        env.event("slot_aside_probe", "", slot=slot.name, ready=False, why=str(error), repo=env.repo)
        return False
    env.store.update(bead.id, BeadPatch(unset_metadata=["aside_level", "aside_probe", "aside_until"]))
    env.event("slot_aside_probe", "", slot=slot.name, ready=True, repo=env.repo)
    return True


def probe(slot: SlotView, *, required: bool = False) -> bool:
    """Caller holds the take lock. Claim before resetting; release even after failure."""
    if not required and slot.slot_bead().metadata.get("aside_probe") != "pending":
        return True
    if not due(slot):
        return False
    try:
        slot.take_locked("slot recovery probe")
    except SlotFail:
        return False
    try:
        return check(slot)
    finally:
        slot.release_locked(None, True, False)
