"""A torn engine lock fails closed: the worktree reads busy, naming the lock file, never free."""
import json
import os
import sys
from pathlib import Path

import pytest
from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import homes
from support.narrow import must

from taskloop.app.slots import engine_lock
from taskloop.contracts import wire
from taskloop.contracts.lockrows import EngineLockRows
from taskloop.contracts.locks import EngineLock as Lock
from taskloop.contracts.wire import Refused


class TornLock(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = Path(tmp.name)
        self.lock = homes.cfg().engine_lock(self.wt)
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text('{"v": 1, "pid": 12')

    def test_the_worktree_is_busy_and_the_message_names_the_file(self) -> None:
        busy = engine_lock.engine_busy(homes.cfg(), self.wt)
        assert str(self.lock) in busy

    def test_take_refuses_and_leaves_the_file(self) -> None:
        why = engine_lock.EngineLock(homes.cfg(), self.wt, "tl-1").take()
        assert str(self.lock) in why
        assert self.lock.read_text() == '{"v": 1, "pid": 12'

    def test_read_engine_lock_refuses(self) -> None:
        with pytest.raises(Refused):
            engine_lock.read_engine_lock(homes.cfg(), self.wt)


def test_a_taken_lock_is_a_row_and_the_worktree_gets_no_engine_file(workdir) -> None:
    lock = engine_lock.EngineLock(homes.cfg(), workdir, "tl-1")
    assert lock.take() == ""
    assert must(EngineLockRows(homes.cfg(), workdir).need()).bead == "tl-1"
    assert not homes.cfg().engine_lock(workdir).exists() and not list(workdir.rglob("engine.*"))
    engine_lock.drop_engine_lock(homes.cfg(), workdir)
    assert not EngineLockRows(homes.cfg(), workdir).exists()


def test_an_older_tls_lock_file_is_read_and_the_next_write_moves_it_into_a_row(workdir) -> None:
    path = homes.cfg().engine_lock(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wire.dump(Lock(pid=os.getpid(), started=1.0, bead="old"))))
    rows = EngineLockRows(homes.cfg(), workdir)
    assert must(rows.need()).bead == "old" and rows.exists()
    engine_lock.EngineLock(homes.cfg(), workdir, "new").write()
    assert not path.exists() and must(rows.need()).bead == "new"


def test_a_row_that_does_not_decode_is_refused_not_read_as_no_lock(workdir) -> None:
    rows = EngineLockRows(homes.cfg(), workdir)
    with rows.rows.transaction() as con:
        con.execute("INSERT INTO lease (kind, name, holder, since, body) VALUES ('run', ?, 'x', 1, ?)", (rows.name, '{"v": 1, "pid": 12'))
    with pytest.raises(Refused):
        engine_lock.read_engine_lock(homes.cfg(), workdir)
    assert rows.get() is None and "engine:" in engine_lock.engine_busy(homes.cfg(), workdir)
