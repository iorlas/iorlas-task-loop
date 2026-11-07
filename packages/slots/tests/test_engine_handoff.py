"""A reexec through uv hands the engine lock to a new Python pid for the same bead."""
from pathlib import Path
from unittest import mock

from tlkernel.env import Env
from tlkernel.locks import EngineLock as Lock
from tlkernel.paths import ConfigDir
from tlkernel.run import Reexec
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

from tlslots import engine_lock
from tlslots.testing import FakeEffects


class ReexecHandoff(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.effects = FakeEffects(alive=True)
        self.fx = self.effects.fx
        self.lock = Lock(pid=101, bead="b-1", by="run-task", start="old", started=1.0)
        for patch in (
            mock.patch.object(engine_lock, "read_engine_lock", return_value=self.lock),
            mock.patch.object(engine_lock.os, "getpid", return_value=202),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def handoff(self, pid: int = 101, bead: str = "b-1") -> Env:
        return Env({"TL_REEXEC": Reexec(run="r", bead=bead, pid=pid, frm="0.1.0").text()})

    def test_reexec_takes_over_the_live_predecessor_for_the_same_bead(self) -> None:
        assert engine_lock.engine_busy(self.cfg, "/wt", self.handoff(), fx=self.fx) == ""

    def test_a_different_pid_or_bead_or_no_reexec_stays_busy(self) -> None:
        for handoff in (self.handoff(pid=303), self.handoff(bead="b-2"), Env(), None):
            with self.subTest(handoff=handoff):
                assert "engine pid 101 runs b-1" in engine_lock.engine_busy(self.cfg, "/wt", handoff, fx=self.fx)

    def test_take_rewrites_the_lock_with_the_new_python_pid(self) -> None:
        self.effects.start = "new"
        with mock.patch.object(engine_lock, "write_engine_lock") as write:
            held = engine_lock.EngineLock(self.cfg, "/wt", "b-1", env=self.handoff(), fx=self.fx)
            assert held.take() == ""
        write.assert_called_once_with(held.cfg, "/wt", held.rec)
        assert (held.rec.pid, held.rec.start, held.rec.bead) == (202, "new", "b-1")

    def test_reexec_does_not_take_over_a_surviving_worker(self) -> None:
        self.effects.workers["b-1"] = ["r303"]
        with mock.patch.object(engine_lock, "read_engine_lock", return_value=self.lock):
            assert "worker run r303" in engine_lock.engine_busy(self.cfg, "/wt", self.handoff(), fx=self.fx)
