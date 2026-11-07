"""pinned.json ({"task-loop": "0.23.38"}, version optional) is written by `tl pin` and `tl rollback` only: the
owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist."""

from tlkernel.paths import ConfigDir
from tlkernel.rowstores import PinStore
from tlkernel.snapshots import Pin


def pin_store(home: ConfigDir) -> PinStore:
    return PinStore(home)


def read_pin(home: ConfigDir) -> Pin:
    """The pin (an empty one when there is none, or the file is not a Pin of this version)."""
    return pin_store(home).get() or Pin()


def pin_version(pin: Pin) -> str:
    return pin.task_loop or ""


def clear_pin(home: ConfigDir) -> bool:
    """Remove the pin; True when there was one."""
    had = pin_store(home).get() is not None
    pin_store(home).delete()
    return had
