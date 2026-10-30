"""EFFECTS: a kill between two effects of the close resumes at the first unapplied one; the bd close happens once."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as T
from support.checkpoints import read_ck

from taskloop.app.run import engine
from taskloop.app.run.closer import Closer
from taskloop.app.wire import slots as wslots
from taskloop.contracts.ids import BeadId
from taskloop.domain import effects as fx
from taskloop.domain import outcome as oc


class Killed(BaseException):
    pass


class CloseResume(T.EngineTest):
    def engine(self) -> engine.Engine:
        c = wslots.load_cfg(str(self.wt))
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store)
        eng.checkpoints.save(step="close")  # the record the keys go into
        return eng

    def closes(self) -> int:
        return sum(1 for c in self.bd_calls if c[:1] == ("close",))

    def test_a_kill_before_each_effect_then_a_restart_applies_the_rest_once(self):
        n = len(fx.plan_close(oc.make(oc.Kind.DONE), dry=False, branch="", slot_gen=0))
        for kill_at in range(n):
            with self.subTest(kill_at=kill_at):
                self.bd_calls.clear()
                eng = self.engine()
                seen: list[fx.Effect] = []
                armed = [True]
                real = Closer.apply

                def dying(self, eff, *a, _seen=seen, _at=kill_at, _real=real, armed=armed):
                    if armed[0] and len(_seen) == _at:
                        armed[0] = False
                        raise Killed
                    _seen.append(eff)
                    _real(self, eff, *a)

                with mock.patch.object(Closer, "apply", dying):
                    with self.assertRaises(Killed):
                        eng.closer.close(oc.make(oc.Kind.DONE))
                    keys = read_ck(eng).applied
                    self.assertEqual(len(keys), kill_at)
                    again = Closer(eng)  # a new process: the ledger is the checkpoint
                    again.close(oc.make(oc.Kind.DONE))
                self.assertEqual(len(seen), n, "every effect ran, none twice")
                self.assertEqual(self.closes(), 1)


if __name__ == "__main__":
    unittest.main()
