"""Late engine crashes retain accepted work and retry its durable cursor."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.checkpoints import read_ck
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest
from support.narrow import must

from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.run import RunState
from taskloop.domain import effects
from taskloop.domain import outcome as oc
from taskloop.domain.lanes import pauses


class EngineCrash(EngineTest):
    def crash_land(self, err):
        def prep(e):
            e.lander.finish = mock.Mock(side_effect=err)
        with mock.patch("taskloop.app.write.check_round.count_tests", return_value=(14, 0)):
            return self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)

    def test_land_crash_keeps_checkpoint_evidence_stats_and_traceback_then_resumes(self):
        rc, _ = self.crash_land(KeyError("stale"))
        e = self.eng
        self.assertEqual(rc, 2)
        self.assertEqual(e.kind.value, "engine_crash")
        self.assertEqual(e.why, "land crashed: KeyError: 'stale'")
        ck = read_ck(e)
        self.assertIsNotNone(ck)
        self.assertEqual(ck.step, "land")
        self.assertTrue(ck.branch)
        self.assertIsNotNone(e.last_run)
        self.assertEqual(e.stores.check_run(e.run_id, None).get(), e.last_run)
        self.assertEqual({k: e.stats[k] for k in ("rounds", "writes", "reviews", "tests_added")},
                         {"rounds": 0, "writes": 1, "reviews": 1, "tests_added": 14})
        self.assertIn("Traceback (most recent call last)", e.log_path.read_text())
        trace = e.stores.traces.read_from(0).items[-1].rec
        self.assertEqual((trace.stats.rounds, trace.stats.writes, trace.stats.reviews, trace.stats.tests_added), (0, 1, 1, 14))
        self.assertEqual(must(RunLocator(e.home).get(e.run_id)).manifest.state, RunState.PARKED)
        park = must(ParkStore(e.home).get(e.bead))
        self.assertEqual((park.reason, park.permanence), ("engine_crash", "transient"))
        self.assertGreater(park.retry_at, park.t)
        self.assertEqual(e.result().retry_after, park.retry_at)
        rc, script = self.run_engine({})
        self.assertEqual(rc, 0)
        self.assertEqual(script.calls, [])
        self.assertIn("going straight to land", self.eng.log_path.read_text())

    def test_write_crash_is_still_an_engine_fault(self):
        def prep(e):
            e.stage_loop.writing.run = mock.Mock(side_effect=KeyError("write"))
        self.run_engine({"plan": [PLAN]}, prep=prep)
        self.assertEqual(self.eng.kind, Kind.FAULT_ENGINE)

    def test_keyboard_interrupt_at_land_still_propagates(self):
        with self.assertRaises(KeyboardInterrupt):
            self.crash_land(KeyboardInterrupt())
        self.assertNotEqual(self.eng.kind.value, "engine_crash")

    def test_system_exit_at_land_still_propagates(self):
        with self.assertRaises(SystemExit):
            self.crash_land(SystemExit(3))
        self.assertNotEqual(self.eng.kind.value, "engine_crash")

    def test_value_error_at_land_keeps_engine_fault_behavior(self):
        self.crash_land(ValueError("refused"))
        self.assertEqual(self.eng.kind, Kind.FAULT_ENGINE)

    def test_continuous_close_crash_parks_and_keeps_its_close_ledger(self):
        def prep(e):
            e.closer.recording.run = mock.Mock(side_effect=KeyError("record"))
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        e = self.eng
        self.assertEqual((rc, e.kind.value, e.why), (2, "engine_crash", "close crashed: KeyError: 'record'"))
        self.assertIsNotNone(read_ck(e))
        self.assertEqual(e.stats["rounds"], 0)
        self.assertIn("Traceback (most recent call last)", e.log_path.read_text())
        self.assertEqual(must(ParkStore(e.home).get(e.bead)).reason, "engine_crash")

    def test_crash_policy_keeps_checkpoint_and_backs_off(self):
        kind = Kind("engine_crash")
        done = oc.make(kind)
        self.assertFalse(done.finished)
        self.assertFalse(any(isinstance(eff, effects.DropCheckpoint)
                             for eff in effects.plan_close(done, dry=False, branch="task/t-1", slot_gen=0)))
        policy = pauses.rule(kind.value)
        self.assertGreater(pauses.delay(policy, 1, lambda: 0.5), pauses.delay(policy, 0, lambda: 0.5))
