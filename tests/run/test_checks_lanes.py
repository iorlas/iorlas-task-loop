"""Whole beads through the Engine, moved out of tests/checks/test_lanes.py (they run the pipeline, not only the checks stage)."""
import threading
from typing import Any

import pytest
from support.engine_case import EngineTest

from tltestkit import procsim
from tltestkit.logs import records

# isort: split
from tlgate.domain.specs import gate_items
from tlpipeline.api import Blocked

UNITY = {"unity": {"limit": 1}}
from checks.test_lanes import spec  # noqa: E402


class Lanes(EngineTest):
    def go(self, checks: list[dict[str, Any]], **cfg: Any) -> Any:
        self.eng = self.checks_engine(checks=checks, **cfg)
        return self.eng.checker.run_items(gate_items(self.eng.cfg))
    def result(self, run: Any, id: str) -> Any:
        return next(c for c in run.results if c.id == id)
    def test_two_lanes_run_at_the_same_time(self):
        meet = threading.Barrier(2, timeout=5)  # a serial run never gets the second party there: the barrier breaks and a check is red
        a = procsim.fake("lane-a", lambda cwd, env: (meet.wait() and 0, ""))
        b = procsim.fake("lane-b", lambda cwd, env: (meet.wait() and 0, ""))
        run = self.go([spec("a", a, "x"), spec("b", b, "y")])
        assert [c.status for c in run.results] == ["passed", "passed"]
    def test_the_steps_of_a_lane_run_in_order(self):
        seen: list[str] = []
        steps = [procsim.fake(f"step-{n}", lambda cwd, env, n=n: (seen.append(n) or 0, "")) for n in "123"]
        run = self.go([spec(f"s{n}", steps[i], "x") for i, n in enumerate("123")] + [spec("o", "true", "y")])
        assert seen == ["1", "2", "3"]
        assert {c.status for c in run.results} == {"passed"}
    def test_a_red_in_one_lane_stops_the_other_and_no_result_of_it_is_green(self):
        slow = procsim.fake("slow", procsim.blocks("partial output"))
        after = procsim.fake("after-slow", procsim.exits(0))
        red = procsim.fake("red", procsim.exits(1, "boom"))
        run = self.go([spec("slow", slow, "x"), spec("after", after, "x"), spec("red", red, "y")])
        stopped, never, bad = self.result(run, "slow"), self.result(run, "after"), self.result(run, "red")
        assert (bad.status, bad.exit) == ("failed", 1)
        for c in (stopped, never):
            assert (c.status, c.exit, c.cancelled) == ("skipped", None, True), c.id
            assert "red failed first" in c.why
        assert run.verdict.value == "red"
        assert [c.id for c in run.failed] == ["red"]
        assert "after-slow" not in [" ".join(k) for k in procsim.WORLD[-1].calls]  # it never started
        again = self.eng.checker.run_items(gate_items(self.eng.cfg))  # nothing of the stopped lane was remembered as green
        assert self.result(again, "slow").cached is False
    def test_a_cancel_frees_the_lease_of_the_check_it_stopped(self):
        held: list[Any] = []
        running = threading.Event()

        def under_lease(cwd, env):
            held.append(self.eng.stores.leases.holders("unity", 1))
            running.set()
            return procsim.blocks()(cwd, env)

        slow = procsim.fake("unity-slow", under_lease)
        red = procsim.fake("red", lambda cwd, env: (running.wait(5) and 1, ""))  # red only once the other lane holds its lease
        self.go([spec("slow", slow, "x", needs=["unity"]), spec("red", red, "y")], resources=UNITY)
        assert len(held) == 1
        assert held[0]  # it did hold the lease while it ran
        assert not self.eng.stores.leases.holders("unity", 1)  # and the cancel gave it back
    def test_a_lane_waiting_for_a_lease_stops_waiting_when_cancelled(self):
        taken, release = threading.Event(), threading.Event()

        def hold():
            with self.eng.stores.leases.acquire("unity", 1, label="another slot"):
                taken.set()
                release.wait(10)

        self.eng = self.checks_engine(checks=[spec("waits", "true", "x", needs=["unity"]), spec("red", "false", "y")], resources=UNITY)
        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        taken.wait(5)
        try:
            run = self.eng.checker.run_items(gate_items(self.eng.cfg))
        finally:
            release.set()
            holder.join(5)
        waits = self.result(run, "waits")
        assert (waits.status, waits.cancelled) == ("skipped", True)
    def test_one_lane_runs_as_before(self):
        run = self.go([spec("a", "true", ""), spec("b", "false", "")])
        assert [c.status for c in run.results] == ["passed", "failed"]

    def test_a_halt_stops_every_lane_and_ends_the_round(self):
        started = threading.Barrier(3, timeout=5)

        def blocked(cwd, env):
            started.wait()
            return procsim.blocks()(cwd, env)

        a, b = procsim.fake("hold-a", blocked), procsim.fake("hold-b", blocked)
        self.eng = self.checks_engine(checks=[spec("a", a, "x"), spec("b", b, "y")])
        threading.Thread(target=lambda: (started.wait(), self.eng.halt.set()), daemon=True).start()
        with pytest.raises(Blocked):
            self.eng.checker.run_items(gate_items(self.eng.cfg))

    def test_the_records_say_the_lane_when_it_began_and_that_it_was_cancelled(self):
        slow = procsim.fake("slow2", procsim.blocks())
        self.go([spec("slow", slow, "x"), spec("red", procsim.fake("red2", procsim.exits(1)), "y")])
        lane = {r["id"]: r["lane"] for r in records(self.eng, "check_start")}
        names = {r["id"]: r["check"] for r in records(self.eng, "check_start")}
        assert {names[i]: v for i, v in lane.items()} == {"diff-check": "", "slow": "x", "red": "y"}
        ends = {names[r["id"]]: r for r in records(self.eng, "check_end")}
        assert (ends["slow"]["cancelled"], ends["red"]["cancelled"]) == (True, False)
        assert (ends["slow"]["lane"], ends["red"]["lane"]) == ("x", "y")
        assert ends["slow"]["at"] >= 0.0
