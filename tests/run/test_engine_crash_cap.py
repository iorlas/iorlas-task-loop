"""Crash recurrence needs an owner; lease loss must never become a crash park."""

import sys
from pathlib import Path
from unittest import mock

import pytest

from taskloop.adapters import beadtools

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import EngineTest

from tlkernel.fence import Fenced
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore
from tlpipeline.api import Standalone, parked_crash
from tlpipeline.testing import FakeBeadClosing, FakeRoundSteps
from tltestkit.narrow import must
from tltestkit.plans import CLEAN, PLAN, WRITE


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
        assert first.run != park.run
        assert park.fingerprint == first.fingerprint
        assert (park.permanence, park.retry_at, park.attempts) == ("needs_owner", 0.0, {"engine:engine_crash": 2})
        assert e.asked
        for text in (e.why, str(self.ask())):
            assert "engine crashed 2 times at test_engine_crash_cap.py:fail_land:" in text
            assert "land crashed: KeyError: 'stale'" in text
            assert "traceback in" in text
            assert e.run_id in text
        assert park.run == e.run_id
        assert "Traceback (most recent call last)" in e.log_path.read_text()

    def test_fourth_different_site_crash_files_owner_ask(self):
        self.crash({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        store = ParkStore(self.eng.home)
        first = must(store.get(self.eng.bead))
        store.put(first.replace(attempts={"engine:engine_crash": 3}, fingerprint="another-site"))
        self.crash({})
        park = must(store.get(self.eng.bead))
        assert (park.permanence, park.retry_at) == ("needs_owner", 0.0)
        assert park.attempts == {"engine:engine_crash": 4}
        assert self.eng.asked
        assert "engine crashed 4 times at" in str(self.ask())

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
            assert e.crash_fingerprint == first
            assert len(first) == 12
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)

    def test_fenced_at_land_is_not_parked(self):
        def prep(e):
            e.lander.finish = mock.Mock(side_effect=Fenced("lease lost"))
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        assert self.eng.fenced == "lease lost"
        assert self.eng.kind != Kind.ENGINE_CRASH
        assert ParkStore(self.eng.home).get(self.eng.bead) is None

    def test_fenced_at_close_propagates_without_park(self):
        def prep(e):
            e.closer.recording.run = mock.Mock(side_effect=Fenced("lease lost"))
        with pytest.raises(Fenced):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        assert self.eng.kind != Kind.ENGINE_CRASH
        assert ParkStore(self.eng.home).get(self.eng.bead) is None

    def test_fenced_single_stage_propagates_without_recording_or_park(self):
        self.crash({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        e = self.eng
        before = must(ParkStore(e.home).get(e.bead))
        runner = Standalone(e, e, e, e, e, rounds=FakeRoundSteps(), once=mock.Mock(), lease=mock.Mock(),
                            closing=FakeBeadClosing(), has_land=lambda: True,
                            repo_of=lambda git, wt: wt, stage_run=mock.Mock(), peek_bead=beadtools.peek)
        with mock.patch.object(runner, "next_step", side_effect=Fenced("lease lost")), \
                mock.patch.object(runner, "record_stage") as record, pytest.raises(Fenced):
            runner.one_stage("land", mock.Mock())
        record.assert_not_called()
        assert ParkStore(e.home).get(e.bead) == before
