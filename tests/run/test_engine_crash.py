"""Late engine crashes retain accepted work and retry its durable cursor."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.checkpoints import read_ck
from support.engine_case import EngineTest
from support.plans import CLEAN, PLAN, WRITE

from tlkernel import closeeffects as effects
from tlkernel import lanepauses as pauses
from tlkernel import runoutcome as oc
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.parks import ParkStore
from tlkernel.run import RunState
from tltestkit.narrow import must


class EngineCrash(EngineTest):
    def crash_land(self, err):
        def prep(e):
            e.lander.finish = mock.Mock(side_effect=err)
        with mock.patch("taskloop.app.write.check_round.count_tests", return_value=(14, 0)):
            return self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)

    def test_land_crash_keeps_checkpoint_evidence_stats_and_traceback_then_resumes(self):
        rc, _ = self.crash_land(KeyError("stale"))
        e = self.eng
        assert rc == 2
        assert e.kind.value == "engine_crash"
        assert e.why == "land crashed: KeyError: 'stale'"
        ck = read_ck(e)
        assert ck is not None
        assert ck.step == "land"
        assert ck.branch
        assert e.last_run is not None
        assert e.stores.check_run(e.run_id, None).get() == e.last_run
        assert (
            {k: e.stats[k] for k in ("rounds", "writes", "reviews", "tests_added")}
            == {"rounds": 0, "writes": 1, "reviews": 1, "tests_added": 14}
        )
        assert "Traceback (most recent call last)" in e.log_path.read_text()
        trace = e.stores.traces.read_from(0).items[-1].rec
        assert (trace.stats.rounds, trace.stats.writes, trace.stats.reviews, trace.stats.tests_added) == (0, 1, 1, 14)
        assert must(RunLocator(e.home).get(e.run_id)).manifest.state == RunState.PARKED
        park = must(ParkStore(e.home).get(e.bead))
        assert (park.reason, park.permanence) == ("engine_crash", "transient")
        assert park.retry_at > park.t
        assert e.retry_after == park.retry_at
        rc, script = self.run_engine({})
        assert rc == 0
        assert script.calls == []
        assert "going straight to land" in self.eng.log_path.read_text()

    def test_write_crash_is_still_an_engine_fault(self):
        def prep(e):
            e.stage_loop.writing.run = mock.Mock(side_effect=KeyError("write"))
        self.run_engine({"plan": [PLAN]}, prep=prep)
        assert self.eng.kind == Kind.FAULT_ENGINE
        assert "Traceback (most recent call last)" in self.eng.log_path.read_text()
        assert "KeyError: 'write'" in self.eng.log_path.read_text()

    def test_keyboard_interrupt_at_land_still_propagates(self):
        with pytest.raises(KeyboardInterrupt):
            self.crash_land(KeyboardInterrupt())
        assert self.eng.kind.value != "engine_crash"

    def test_system_exit_at_land_still_propagates(self):
        with pytest.raises(SystemExit):
            self.crash_land(SystemExit(3))
        assert self.eng.kind.value != "engine_crash"

    def test_value_error_at_land_parks_with_checkpoint_and_traceback(self):
        self.crash_land(ValueError("refused"))
        assert self.eng.kind == Kind.PAUSE_LANE
        assert must(ParkStore(self.eng.home).get(self.eng.bead)).reason == "stage_refused"
        assert self.eng.asked
        assert "crashing" not in str(self.ask())
        assert "crashed" not in self.eng.why
        assert must(read_ck(self.eng)).step == "land"
        assert "ValueError: refused" in self.eng.log_path.read_text()
        assert "Traceback (most recent call last)" in self.eng.log_path.read_text()

    def test_a_close_projection_crash_keeps_the_winner_and_its_close_ledger(self):
        def prep(e):
            e.closer.recording.run = mock.Mock(side_effect=KeyError("record"))
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, prep=prep)
        e = self.eng
        assert (rc, e.kind.value, e.why) == (0, "landed", "")
        assert read_ck(e) is not None
        assert e.stats["rounds"] == 0
        assert "Traceback (most recent call last)" in e.log_path.read_text()
        assert "KeyError: 'record'" in e.log_path.read_text()
        assert ParkStore(e.home).get(e.bead) is None
        manifest = must(RunLocator(e.home).get(e.run_id)).manifest
        assert (manifest.state, manifest.sha) == (RunState.DONE, e.landed_sha)

    def test_crash_policy_keeps_checkpoint_and_backs_off(self):
        kind = Kind("engine_crash")
        done = oc.make(kind)
        assert not done.finished
        assert not any(isinstance(eff, effects.DropCheckpoint)
                             for eff in effects.plan_close(done, dry=False, branch="task/t-1", slot_gen=0))
        policy = pauses.rule(kind.value)
        assert pauses.delay(policy, 1, lambda: 0.5) > pauses.delay(policy, 0, lambda: 0.5)
