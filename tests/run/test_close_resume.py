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

from taskloop.app.run import ended, engine
from taskloop.app.run.closer import Closer, closer_over
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.domain import effects as fx
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs


class Killed(BaseException):
    pass


class Base(T.EngineTest):
    def engine(self) -> engine.Engine:
        c = wslots.load_cfg(str(self.wt))
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot())
        eng.checkpoints.save(step="close")  # the record the keys go into
        return eng

    def closes(self) -> int:
        return sum(1 for c in self.bd_calls if c[:1] == ("close",))


class CloseResume(Base):
    def test_a_kill_before_each_effect_then_a_restart_applies_the_rest_once(self):
        n = len(fx.plan_close(oc.make(Kind.DONE), dry=False, branch="", slot_gen=0))
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
                        eng.closer.close(oc.make(Kind.DONE))
                    keys = read_ck(eng).applied
                    self.assertEqual(len(keys), kill_at)
                    again = closer_over(eng)  # a new process: the ledger is the checkpoint
                    again.close(oc.make(Kind.DONE))
                self.assertEqual(len(seen), n, "every effect ran, none twice")
                self.assertEqual(self.closes(), 1)


class ColdRestart(Base):
    """The process dies (nothing in memory survives): a new engine finds the close in the checkpoint and finishes it by itself."""

    def killed_at(self, kind_at, outcome=None, leftovers=()):
        """An engine whose close dies before the effect of type `kind_at`; -> the dead engine."""
        eng = self.engine()
        eng.leftovers = [dict(lo) for lo in leftovers]
        real = Closer.apply

        def dying(this, eff, *a):
            if isinstance(eff, kind_at):
                raise Killed
            real(this, eff, *a)

        with mock.patch.object(Closer, "apply", dying), self.assertRaises(Killed):
            eng.closer.close(outcome or oc.make(Kind.DONE))
        return eng

    def cold(self):
        c = wslots.load_cfg(str(self.wt))
        return engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot())

    def test_a_new_process_takes_the_dead_runs_id_from_its_checkpoint(self):
        dead = self.killed_at(fx.CloseBead)
        again = self.cold()
        self.assertEqual(again.log_path.stem, dead.log_path.stem)
        self.assertIsNotNone(again.dead)

    def test_a_closed_run_leaves_nothing_to_finish(self):
        eng = self.engine()
        eng.closer.close(oc.make(Kind.FAULT_INFRA, "failed: infrastructure x"))  # not finished: the checkpoint stays, whole
        self.assertIsNone(self.cold().dead)

    def test_the_restarted_process_applies_the_remaining_effects_and_closes_the_bead_once(self):
        self.killed_at(fx.CloseBead)
        before = self.closes()
        self.assertEqual(before, 0)
        again = self.cold()
        again.run()
        self.assertEqual(self.closes(), 1)
        self.assertIsNone(read_ck(again))  # the finished run's checkpoint went last
        again2 = self.cold()  # a third process finds nothing to do
        self.assertIsNone(again2.dead)

    def test_a_kill_before_each_effect_then_a_cold_restart_closes_the_bead_once(self):
        for at in (fx.SaveBranch, fx.RecordRun, fx.FileNotes, fx.Reflect, fx.CloseBead, fx.ReleaseSlot, fx.DropCheckpoint):
            with self.subTest(at=at.__name__):
                self.bd_calls.clear()
                self.killed_at(at)
                self.cold().run()
                self.assertEqual(self.closes(), 1)

    def test_reflect_says_the_counts_FileNotes_stored_not_what_memory_has_after_a_kill(self):
        lo = [{"title": "Leftover one", "why": "later"}, {"title": "Leftover two", "why": "later"}]
        self.killed_at(fx.Reflect, leftovers=lo)
        self.assertEqual(read_ck(self.cold()).notes.filed, 2)
        creates = sum(1 for c in self.bd_calls if c[:1] == ("create",))
        self.assertEqual(creates, 2)
        again = self.cold()
        again.run()
        reflect = [c[3] for c in self.store.said("comments", "add") if c[3].startswith("Reflect (engine)")]
        self.assertEqual(len(reflect), 1)
        self.assertIn("filed=2;", reflect[0])
        self.assertEqual(sum(1 for c in self.bd_calls if c[:1] == ("create",)), 2, "nothing filed twice")

    def test_an_ask_outcome_keeps_its_spec_through_the_checkpoint_and_the_bead_is_blocked_once(self):
        spec = askspecs.external_fact(["x"])
        ask = oc.make(Kind.ASK_DECISION, "needs a fact", spec=spec)
        self.assertEqual(ended.loaded(ended.stored("r", ask, None, "", []))[0], ask)
        self.killed_at(fx.BlockBead, outcome=ask)
        self.cold().run()
        self.assertEqual(sum(1 for c in self.bd_calls if c[:1] == ("block",) or "blocked" in c), 1)


if __name__ == "__main__":
    unittest.main()
