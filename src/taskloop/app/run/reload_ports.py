"""Root adapters for the current run lock."""
from taskloop.app.slots import engine_lock


def locked_slot() -> str:
    """The slot held by this process, or empty outside a slot."""
    lock = engine_lock.LOCK
    return lock.rec.slot if lock else ""
