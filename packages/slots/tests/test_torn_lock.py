"""A torn engine lock fails closed: the worktree reads busy, naming the lock file, never free."""
from pathlib import Path

import pytest
from tlkernel.lockrows import EngineLockRows
from tlkernel.paths import ConfigDir
from tlkernel.wire import Refused
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory

from tlslots import engine_lock
from tlslots.testing import FakeEffects

TORN = '{"v": 1, "pid": 12'


class TornLock(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = Path(tmp.name) / "wt"
        self.wt.mkdir()
        self.cfg = ConfigDir(Path(tmp.name) / "config")
        self.rows = EngineLockRows(self.cfg, self.wt)
        with self.rows.rows.transaction() as con:
            con.execute("INSERT INTO lease (kind, name, holder, since, body) VALUES ('run', ?, 'x', 1, ?) "
                        "ON CONFLICT(kind, name) DO UPDATE SET body=excluded.body", (self.rows.name, TORN))

    def test_the_worktree_is_busy_and_the_message_names_the_lock(self) -> None:
        assert self.rows.name in engine_lock.engine_busy(self.cfg, self.wt, fx=FakeEffects().fx)

    def test_take_refuses_and_leaves_the_row(self) -> None:
        why = engine_lock.EngineLock(self.cfg, self.wt, "tl-1", fx=FakeEffects().fx).take()
        assert self.rows.name in why
        assert self.rows.body() == TORN

    def test_read_engine_lock_refuses(self) -> None:
        with pytest.raises(Refused):
            engine_lock.read_engine_lock(self.cfg, self.wt)


def test_a_taken_lock_is_a_row_and_the_worktree_gets_no_engine_file(workdir) -> None:
    lock = engine_lock.EngineLock(ConfigDir(workdir / "config"), workdir, "tl-1", fx=FakeEffects().fx)
    assert lock.take() == ""
    assert must(EngineLockRows(ConfigDir(workdir / "config"), workdir).need()).bead == "tl-1"
    assert not list(workdir.rglob("engine.*"))
    engine_lock.drop_engine_lock(ConfigDir(workdir / "config"), workdir)
    assert not EngineLockRows(ConfigDir(workdir / "config"), workdir).exists()


def test_a_row_that_does_not_decode_is_refused_not_read_as_no_lock(workdir) -> None:
    rows = EngineLockRows(ConfigDir(workdir / "config"), workdir)
    with rows.rows.transaction() as con:
        con.execute("INSERT INTO lease (kind, name, holder, since, body) VALUES ('run', ?, 'x', 1, ?)", (rows.name, '{"v": 1, "pid": 12'))
    with pytest.raises(Refused):
        engine_lock.read_engine_lock(ConfigDir(workdir / "config"), workdir)
    assert rows.get() is None and "engine:" in engine_lock.engine_busy(ConfigDir(workdir / "config"), workdir, fx=FakeEffects().fx)
