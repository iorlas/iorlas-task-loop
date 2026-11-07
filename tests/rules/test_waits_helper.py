"""Test-side polling must fail instead of hanging a worker."""
import itertools
import time
from unittest.mock import Mock

import pytest
from support import waits

from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord
from tltestkit.memdoc import MemLockTable


def test_settle_fails_at_its_limit():
    index = Mock()
    index.pass_once.return_value = False
    start = time.monotonic()
    with pytest.raises(AssertionError, match=r"indexer did not settle in 0\.05 s"):
        waits.settle(index, limit=0.05)
    assert 0.05 <= time.monotonic() - start < 0.5


def test_settle_returns_when_index_finishes():
    index = Mock()
    index.pass_once.side_effect = [False, False, True]
    waits.settle(index, budget=0.2)
    assert index.pass_once.call_count == 3
    index.pass_once.assert_called_with(budget=0.2)


def test_memory_lock_with_a_live_holder_has_a_safety_deadline(monkeypatch):
    table = MemLockTable(alive=lambda pid: True)
    table.plant(LockWhat.LAND, "repo", LockRecord(what=LockWhat.LAND, holder="stuck", pid=123, t=0))
    ticks = itertools.count(0, 10)
    monkeypatch.setattr("support.memstores.time.monotonic", lambda: next(ticks))
    polls = 0

    def wait(timeout):
        nonlocal polls
        polls += 1
        if polls > 5:
            raise RuntimeError("lock loop exceeded watchdog")

    monkeypatch.setattr(table.cond, "wait", wait)
    with pytest.raises(AssertionError, match="lock land-repo did not settle in 30 s"), table.hold(LockWhat.LAND, "repo", "waiter"):
        pytest.fail("acquired a held lock")
