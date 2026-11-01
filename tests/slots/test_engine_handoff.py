"""A reexec through uv hands the engine lock to a new Python pid for the same bead."""
import contextlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.slots import engine_lock
from taskloop.contracts.env import Env
from taskloop.contracts.locks import EngineLock as Lock
from taskloop.contracts.run import Reexec


class ReexecHandoff(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = Lock(pid=101, bead="b-1", by="run-task", start="old", started=1.0)
        for patch in (
            mock.patch.object(engine_lock, "read_engine_lock", return_value=self.lock),
            mock.patch.object(engine_lock.os, "getpid", return_value=202),
            mock.patch.object(engine_lock, "proc_alive", return_value=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def handoff(self, pid: int = 101, bead: str = "b-1") -> Env:
        return Env({"TL_REEXEC": Reexec(run="r", bead=bead, pid=pid, frm="0.1.0").text()})

    def test_reexec_takes_over_the_live_predecessor_for_the_same_bead(self) -> None:
        self.assertEqual(engine_lock.engine_busy("/wt", self.handoff()), "")

    def test_a_different_pid_or_bead_or_no_reexec_stays_busy(self) -> None:
        for handoff in (self.handoff(pid=303), self.handoff(bead="b-2"), Env(), None):
            with self.subTest(handoff=handoff):
                self.assertIn("engine pid 101 runs b-1", engine_lock.engine_busy("/wt", handoff))

    def test_take_rewrites_the_lock_with_the_new_python_pid(self) -> None:
        with mock.patch.object(engine_lock, "hold_path", return_value=contextlib.nullcontext()), \
                mock.patch.object(engine_lock, "proc_start", return_value="new"), \
                mock.patch.object(engine_lock, "write_engine_lock") as write:
            held = engine_lock.EngineLock("/wt", "b-1", env=self.handoff())
            self.assertEqual(held.take(), "")
        write.assert_called_once_with("/wt", held.rec)
        self.assertEqual((held.rec.pid, held.rec.start, held.rec.bead), (202, "new", "b-1"))

    def test_reexec_does_not_take_over_a_surviving_worker(self) -> None:
        lock = self.lock.replace(workers=[(303, "worker")])
        with mock.patch.object(engine_lock, "read_engine_lock", return_value=lock):
            self.assertIn("worker pid 303", engine_lock.engine_busy("/wt", self.handoff()))


if __name__ == "__main__":
    unittest.main()
