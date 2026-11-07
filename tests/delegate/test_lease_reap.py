"""An orphaned worker is stopped with the state lock free, so a stop of seconds blocks no other route.py's claim (tl-sqd3.24, M10)."""
from unittest import mock

import hermetic  # noqa: F401

from delegate.app import env, lease
from delegate.app.lease import RunLease
from delegate.contracts import stores
from delegate.contracts.state import Lease


def seed(rid: str, task: str) -> None:
    env.update_state(lambda s: s.leases.__setitem__(rid, Lease(
        lane="L", role="worker", pid=1, pid_start="gone", start=env.now() - 300, expires=env.now() + 60, task=task,
        worker_pid=4242, worker_start="w")))


def claim_with(reap) -> tuple[RunLease, object]:
    mine = RunLease("new", "worker", "T-7", "L", "m", None, False, 60.0)
    reaped = {"done": False}

    def fake_reap(v):
        reap()
        reaped["done"] = True
        return True

    with (mock.patch.object(lease, "orphan", side_effect=lambda v: not reaped["done"]), mock.patch.object(lease, "reap", fake_reap)):
        return mine, mine.claim()


def test_the_reap_runs_while_the_state_lock_is_free():
    seed("old", "T-7")
    seen: list[bool] = []

    def reap():
        try:
            with stores.locked(env.states().path, timeout=0.2):
                seen.append(True)
        except TimeoutError:
            seen.append(False)

    _, no = claim_with(reap)
    assert seen == [True]  # another claim could have taken the lock meanwhile
    assert no is None  # the reaped worker's task is free again
    assert "old" not in env.load_state().leases and "new" in env.load_state().leases


def test_a_worker_that_survives_the_reap_keeps_its_task_blocked():
    seed("old", "T-7")
    mine = RunLease("new", "worker", "T-7", "L", "m", None, False, 60.0)
    with mock.patch.object(lease, "orphan", return_value=True), mock.patch.object(lease, "reap", return_value=False):
        no = mine.claim()
    assert no is not None and no[0] == "duplicate_task"
    assert "old" in env.load_state().leases
