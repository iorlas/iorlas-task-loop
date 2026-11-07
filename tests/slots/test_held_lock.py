"""A run's slot readers follow its own held lock through acquisition and cleanup."""
from types import SimpleNamespace
from unittest.mock import Mock

from taskloop.app.run.reload_ports import locked_slot
from taskloop.app.slots.engine_lock import EngineLock, HeldLock


def test_slot_reader_follows_only_its_runs_lock():
    held, other = HeldLock(), HeldLock()
    lock = Mock(spec=EngineLock)
    lock.rec = SimpleNamespace(slot="slot-a")
    assert locked_slot(held) == ""
    held.set(lock)
    assert locked_slot(held) == "slot-a"
    assert locked_slot(other) == ""
    lock.rec = SimpleNamespace(slot="slot-b")
    assert locked_slot(held) == "slot-b"
    held.clear()
    assert locked_slot(held) == ""
    lock.release.assert_not_called()
