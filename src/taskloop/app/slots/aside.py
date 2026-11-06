"""A failed reset excludes a slot until a real reset and setup probe passes."""
from taskloop.app.slots.reset import setup
from taskloop.app.slots.surface import SlotView
from taskloop.contracts.beadsport import BdFailure, BeadPatch
from taskloop.contracts.slots import SlotFail, SlotGitError


def check(slot: SlotView) -> bool:
    """Probe a claimed slot, including setup even when its inputs have not changed."""
    env, bead = slot.env, slot.slot_bead()
    try:
        slot.ready_for("")
        setup(slot, force=True)
    except (SlotFail, SlotGitError, BdFailure, OSError) as error:
        env.store.update(bead.id, BeadPatch(set_metadata={"aside_probe": "pending"}))
        env.event("slot_aside_probe", "", slot=slot.name, ready=False, why=str(error), repo=env.repo)
        return False
    env.store.update(bead.id, BeadPatch(unset_metadata=["aside_level", "aside_probe"]))
    env.event("slot_aside_probe", "", slot=slot.name, ready=True, repo=env.repo)
    return True


def probe(slot: SlotView, *, required: bool = False) -> bool:
    """Caller holds the take lock. Claim before resetting; release even after failure."""
    if not required and slot.slot_bead().metadata.get("aside_probe") != "pending":
        return True
    try:
        slot.take_locked("slot recovery probe")
    except SlotFail:
        return False
    try:
        return check(slot)
    finally:
        slot.release_locked(None, True, False)
