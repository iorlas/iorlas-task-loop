"""The Lease heartbeat thread: stop() joins it, and a beat that raises ends it with the death told, not lost (tl-7i9k.28)."""
import threading
from unittest import mock

from taskloop.app.slots.lease import Lease


def test_stop_joins_the_thread_so_none_outlives_its_owner():
    lease = Lease(mock.Mock(), "a", every=0.001).start()
    lease.stop()
    assert not lease.thread.is_alive()


def test_a_beat_that_raises_ends_the_thread_and_is_told_to_on_death():
    told: list[BaseException] = []
    seen = threading.Event()
    store = mock.Mock()
    store.heartbeat.side_effect = RuntimeError("boom")
    lease = Lease(store, "a", every=0.001, on_death=lambda err: (told.append(err), seen.set())).start()
    assert seen.wait(5)
    lease.stop()
    assert [str(e) for e in told] == ["boom"] and lease.died is told[0] and not lease.thread.is_alive()
