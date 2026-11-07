"""Whole beads through the Engine, moved out of tests/checks/test_resources.py (they run the pipeline, not only the checks stage)."""
import sys
import threading
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import EngineTest

from tltestkit.logs import records
from tltestkit.plans import CLEAN, PLAN, WRITE

# isort: split

from taskloop.app.plan.planner import Planner
from tlgate import resources
from tlkernel.config import HostResources
from tlpipeline.api import Waits

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
UNITY = {"unity": {"limit": 1}}



class Engine(EngineTest):
    def lacking(self, eng):
        eng.stores.host.write(HostResources(resources=[]))
    def checks(self, inputs, cmd="true"):
        return [{"id": "ut", "cmd": cmd, "run": "both", "inputs": inputs, "needs": ["unity"]}]

    def test_the_wait_for_the_lease_is_recorded_on_the_check_result_and_its_end_row(self):
        gate, polled = threading.Event(), threading.Event()  # the holder has the lease; the check polled and found it taken
        real_start = Waits.start

        def start(waits, what, *a, **kw):
            polled.set()  # the check's first wait is its first poll that lost
            return real_start(waits, what, *a, **kw)

        def hold_it(eng):
            def hold():
                with eng.stores.leases.acquire("unity", 1, label="other:slot"):
                    gate.set()
                    polled.wait(30)  # freed only after the check lost a poll, however slow the engine start is
                    time.sleep(0.25)  # a fixed hold after that: the check waits at least this long

            threading.Thread(target=hold, daemon=True).start()
            gate.wait(5)

        with mock.patch.object(resources, "POLL_S", 0.02), mock.patch.object(Waits, "start", start):
            rc, _ = self.run_engine(ANSWERS, prep=hold_it, resources=UNITY, checks=self.checks(["f.txt"]))
        assert rc == 0, self.blocked
        waits = sorted(r["wait_seconds"] for r in records(self.eng, "check_end"))
        assert waits[-1] >= 0.2, waits  # the unity check queued behind the other slot's lease
        assert waits[:-1] == [0.0] * (len(waits) - 1)  # and no other check waited
        (begin,), (end,) = records(self.eng, "wait_start"), records(self.eng, "wait_end")
        assert (begin["holder"], begin["check"], end["check"]) == ("other:slot", "ut", "ut")

    def test_a_host_without_the_resource_lands_when_the_diff_leaves_the_inputs_alone(self):
        rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=self.checks(["client/**"]))
        assert rc == 0, self.blocked
        assert records(self.eng, "gate_end")[-1]["deferred"] == ["ut"]
        notes = " ".join(str(r.get("text", "")) for r in records(self.eng, "note"))
        assert "deferred checks" in notes
        assert "ut" in notes

    def test_a_plan_that_touches_the_inputs_moves_the_bead_before_any_code_is_written(self):
        rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=self.checks(["f.txt"]))
        assert rc != 0
        r = self.eng.result()
        assert (r.outcome, r.kind) == ("paused", "pause_moved")
        assert "labelled needs:unity" in r.why
        assert self.store.said("label", "add") == [("label", "add", "t-1", "needs:unity")]
        assert records(self.eng, "gate_end") == []

    def test_a_diff_that_hits_the_inputs_the_plan_did_not_name_moves_the_bead_at_the_land(self):
        with mock.patch.object(Planner, "move_if_lacking"):  # the plan did not see it: the land is the second look
            rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=[dict(self.checks(["f.txt"])[0], run="gate")])
        assert rc != 0
        r = self.eng.result()
        assert (r.outcome, r.kind) == ("paused", "pause_moved")
        assert self.store.said("label", "add") == [("label", "add", "t-1", "needs:unity")]
        assert self.store.said("close") == []
        assert [g["exit"] for g in records(self.eng, "gate_end")] == [1]  # it got as far as the land's gate

    def test_a_host_that_has_the_resource_adds_no_label_and_lands(self):
        rc, _ = self.run_engine(ANSWERS, resources=UNITY, checks=self.checks(["f.txt"]))
        assert rc == 0, self.blocked
        assert self.store.said("label", "add") == []
