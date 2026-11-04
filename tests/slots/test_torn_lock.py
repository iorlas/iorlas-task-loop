"""A torn engine lock fails closed: the worktree reads busy, naming the lock file, never free."""
import sys
import tempfile
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.slots import engine_lock
from taskloop.contracts.wire import Refused


class TornLock(Case):
    def setup_method(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = Path(tmp.name)
        self.lock = engine_lock.engine_lock_path(self.wt)
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text('{"v": 1, "pid": 12')

    def test_the_worktree_is_busy_and_the_message_names_the_file(self) -> None:
        busy = engine_lock.engine_busy(self.wt)
        assert str(self.lock) in busy

    def test_take_refuses_and_leaves_the_file(self) -> None:
        why = engine_lock.EngineLock(self.wt, "tl-1").take()
        assert str(self.lock) in why
        assert self.lock.read_text() == '{"v": 1, "pid": 12'

    def test_read_engine_lock_refuses(self) -> None:
        with pytest.raises(Refused):
            engine_lock.read_engine_lock(self.wt)
