"""Crash recurrence needs an owner; lease loss must never become a crash park."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest
from support.narrow import must

from taskloop.app.run.crash import parked_crash
from taskloop.app.run.stages import one_stage
from taskloop.contracts.fence import Fenced
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import ParkStore


def fail_land(bead):
    raise KeyError("stale")


class CrashCap(EngineTest):
    def crash(self, answers):
        def prep(e):
            e.lander.finish = fail_land
        return self.run_engine(answers, prep=prep)

    def test_second_same_site_crash_files_owner_ask_with_count_site_why_and_run(self):
        self.crash({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        first = must(ParkStore(self.eng.home).get(self.eng.bead))
        self.crash({})
        e = self.eng
        park = must(ParkStore(e.home).get(e.bead))
        self.assertNotEqual(first.run, park.run)
        self.assertEqual(park.fingerprint, first.fingerprint)
        self.assertEqual((park.permanence, park.retry_at, park.attempts), ("needs_owner", 0.0, {"engine_crash": 2}))
        self.assertTrue(e.asked)
        for text in (e.why, str(self.ask())):
            self.assertIn("engine crashed 2 times at test_engine_crash_cap.py:fail_land:", text)
            self.assertIn("land crashed: KeyError: 'stale'", text)
            self.assertIn("traceback in", text)
            self.assertIn(e.run_id, text)
        self.assertEqual(park.run, e.run_id)
        self.assertIn("Traceback (most recent call last)", e.log_path.read_text())

    def test_fourth_different_site_crash_files_owner_ask(self):
        self.crash({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        store = ParkStore(self.eng.home)
        first = must(store.get(self.eng.bead))
        store.put(first.replace(attempts={"engine_crash": 3}, fingerprint="another-site"))
        self.crash({})
        park = must(store.get(self.eng.bead))
        self.assertEqual((park.permanence, park.retry_at), ("needs_owner", 0.0))
        self.assertEqual(park.attempts, {"engine_crash": 4})
        self.assertTrue(self.eng.asked)
        self.assertIn("engine crashed 4 times at", str(self.ask()))

    def test_fingerprint_ignores_exception_message(self):
        def prep(e):
            errors = []
            for message in ("one", "two"):
                try:
                    raise KeyError(message)
                except KeyError as err:
                    errors.append(err)
            parked_crash(e, "land", errors[0])
            first = e.crash_fingerprint
            parked_crash(e, "land", errors[1])
            self.assertEqual(e.crash_fingerprint, first)
            self.assertEqual(len(first), 12)
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)

    def test_fenced_at_land_is_not_parked(self):
        def prep(e):
            e.lander.finish = mock.Mock(side_effect=Fenced("lease lost"))
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        self.assertEqual(self.eng.fenced, "lease lost")
        self.assertNotEqual(self.eng.kind, Kind.ENGINE_CRASH)
        self.assertIsNone(ParkStore(self.eng.home).get(self.eng.bead))

    def test_fenced_at_close_propagates_without_park(self):
        def prep(e):
            e.closer.recording.run = mock.Mock(side_effect=Fenced("lease lost"))
        with self.assertRaises(Fenced):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        self.assertNotEqual(self.eng.kind, Kind.ENGINE_CRASH)
        self.assertIsNone(ParkStore(self.eng.home).get(self.eng.bead))

    def test_fenced_single_stage_propagates_without_recording_or_park(self):
        self.crash({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        e = self.eng
        before = must(ParkStore(e.home).get(e.bead))
        with mock.patch("taskloop.app.run.stages.next_step", side_effect=Fenced("lease lost")), \
                mock.patch("taskloop.app.run.stages.record_stage") as record, self.assertRaises(Fenced):
            one_stage(e, "land", mock.Mock())
        record.assert_not_called()
        self.assertEqual(ParkStore(e.home).get(e.bead), before)
