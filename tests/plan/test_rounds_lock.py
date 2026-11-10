"""One rounds process per (factory.db, backlog): the real lock library over a lock file under tmp_path; nonreentrant, so
a second take in this process is refused as another process's would be."""

import os
from pathlib import Path

import pytest

from taskloop.rounds_lock import RoundsLockUnavailable, RoundsRunning, hold, lock_path


def test_a_second_hold_for_the_same_backlog_is_refused_naming_the_holder(tmp_path: Path) -> None:
    db = tmp_path / "factory.db"
    assert lock_path(db, "tasks") == tmp_path / "factory.db.rounds-tasks.lock"
    held = hold(db, "tasks")
    try:
        with pytest.raises(RoundsRunning) as refused:
            hold(db, "tasks")
        assert refused.value.pid == os.getpid() and f"pid {os.getpid()}" in str(refused.value)
        hold(db, "other").release()  # another backlog has its own lock
    finally:
        held.release()
    hold(db, "tasks").release()  # free again once its holder lets go
    assert not db.exists()  # nothing but the lock file beside it


def test_a_lock_file_that_cannot_be_made_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("")
    with pytest.raises(RoundsLockUnavailable):
        hold(tmp_path / "file" / "factory.db", "tasks")
