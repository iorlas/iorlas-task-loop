"""GATETRACKS (tl-7k8.2): checks carry a track; the steps of a track run in order, the tracks run in parallel, and the first red cancels the
other tracks (their own process groups only, through the Spawner) and the round is red. procsim fakes, no real spawn; the tree kill is
tests/checks/real/test_tracks_real.py."""
import threading
import time
from typing import Any

import pytest
from support.check_host import CheckHostCase

from tltestkit import procsim
from tltestkit.case import Case

# isort: split
from tlgate import tracks
from tlgate.domain.plan import CheckPlan, Step
from tlgate.domain.specs import gate_items
from tlgate.round import Round
from tlkernel.checks import Check
from tlkernel.config import ConfigError, load
from tlkernel.ids import CheckId

UNITY = {"unity": {"limit": 1}}


def spec(id: str, cmd: str, track: str, **more: Any) -> dict[str, Any]:
    return {"id": id, "cmd": cmd, "run": "gate", "track": track, **more}


class Tracks(CheckHostCase):
    def go(self, checks: list[dict[str, Any]], **cfg: Any) -> Any:
        self.eng = self.checks_engine(checks=checks, **cfg)
        return self.eng.checker.run_items(gate_items(self.eng.cfg))

    def result(self, run: Any, id: str) -> Any:
        return next(c for c in run.results if c.id == id)

    def test_two_tracks_run_at_the_same_time(self):
        meet = threading.Barrier(2, timeout=5)  # a serial run never gets the second party there: the barrier breaks and a check is red
        a = procsim.fake("track-a", lambda cwd, env: (meet.wait() and 0, ""))
        b = procsim.fake("track-b", lambda cwd, env: (meet.wait() and 0, ""))
        run = self.go([spec("a", a, "x"), spec("b", b, "y")])
        assert [c.status for c in run.results] == ["passed", "passed"]

    def test_the_steps_of_a_track_run_in_order(self):
        seen: list[str] = []
        steps = [procsim.fake(f"step-{n}", lambda cwd, env, n=n: (seen.append(n) or 0, "")) for n in "123"]
        run = self.go([spec(f"s{n}", steps[i], "x") for i, n in enumerate("123")] + [spec("o", "true", "y")])
        assert seen == ["1", "2", "3"]
        assert {c.status for c in run.results} == {"passed"}

    def test_a_red_in_one_track_stops_the_other_and_no_result_of_it_is_green(self):
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
        again = self.eng.checker.run_items(gate_items(self.eng.cfg))  # nothing of the stopped track was remembered as green
        assert self.result(again, "slow").cached is False

    def test_a_cancel_frees_the_lease_of_the_check_it_stopped(self):
        held: list[Any] = []
        running = threading.Event()

        def under_lease(cwd, env):
            held.append(self.eng.stores.leases.holders("unity", 1))
            running.set()
            return procsim.blocks()(cwd, env)

        slow = procsim.fake("unity-slow", under_lease)
        red = procsim.fake("red", lambda cwd, env: (running.wait(5) and 1, ""))  # red only once the other track holds its lease
        self.go([spec("slow", slow, "x", needs=["unity"]), spec("red", red, "y")], resources=UNITY)
        assert len(held) == 1
        assert held[0]  # it did hold the lease while it ran
        assert not self.eng.stores.leases.holders("unity", 1)  # and the cancel gave it back

    def test_a_track_waiting_for_a_lease_stops_waiting_when_cancelled(self):
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



    def test_one_track_runs_as_before(self):
        run = self.go([spec("a", "true", ""), spec("b", "false", "")])
        assert [c.status for c in run.results] == ["passed", "failed"]


class Config(Case):
    def test_a_track_is_a_name_and_an_unknown_key_is_refused(self):
        ok = load({"engine": {"checks": [{"id": "a", "argv": ["true"], "track": "light"}]}})
        assert ok.engine.checks[0].track == "light"
        with pytest.raises(ConfigError):
            load({"engine": {"checks": [{"id": "a", "argv": ["true"], "tracks": "light"}]}})
        with pytest.raises(ConfigError):
            load({"engine": {"checks": [{"id": "a", "argv": ["true"], "track": 3}]}})

    def test_a_check_may_not_read_a_check_of_another_track(self):
        checks = [{"id": "a", "argv": ["true"], "track": "x"}, {"id": "b", "argv": ["true"], "track": "y", "reads": ["a"]}]
        with pytest.raises(ConfigError) as cm:
            load({"engine": {"checks": checks}})
        assert "track" in str(cm.value)
        checks[1]["track"] = "x"
        load({"engine": {"checks": checks}})


class RunStopped(RuntimeError):
    pass


class StopHost:
    def __init__(self, started: threading.Event) -> None:
        self.started = started
        self.calls = 0
        self.error = RunStopped("stopped")

    def halt_point(self, when: bool = True, wait: float = 0) -> None:
        assert self.started.wait(2)
        self.calls += 1
        if self.calls == 2:
            raise self.error


def test_stop_reports_a_stuck_track(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    # Start FD capture in the call phase: the setup stream bridge otherwise restores its closed setup stream.
    capfd = request.getfixturevalue("capfd")
    monkeypatch.setattr(tracks, "STOP_JOIN_S", 0.2)
    started, release = threading.Event(), threading.Event()
    workers: list[threading.Thread] = []
    host = StopHost(started)

    def step(item: Step, n: int, st: Round) -> None:
        workers.append(threading.current_thread())
        started.set()
        release.wait()

    plan = CheckPlan((Step(Check(id=CheckId("blocked"), cmd="true"), (), ()),))
    before = time.monotonic()
    try:
        with pytest.raises(tracks.TrackStuck) as caught:
            tracks.Tracks(host, step, lambda *args: None).run(plan, {"blocked": [0]}, Round(1))
        assert time.monotonic() - before < 5
        assert "track-blocked" in str(caught.value)
        assert "0.2" in str(caught.value)
        assert caught.value.__cause__ is host.error
        stderr = capfd.readouterr().err
        assert "Thread track-blocked (" in stderr
        assert "in step" in stderr
    finally:
        release.set()
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()


def test_stop_reraises_original_when_track_ends(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    capfd = request.getfixturevalue("capfd")
    monkeypatch.setattr(tracks, "STOP_JOIN_S", 0.2)
    started = threading.Event()
    host = StopHost(started)

    def step(item: Step, n: int, st: Round) -> None:
        assert st.cancel is not None
        started.set()
        assert st.cancel.wait(2)

    plan = CheckPlan((Step(Check(id=CheckId("prompt"), cmd="true"), (), ()),))
    with pytest.raises(RunStopped) as caught:
        tracks.Tracks(host, step, lambda *args: None).run(plan, {"prompt": [0]}, Round(1))
    assert caught.value is host.error
    assert capfd.readouterr().err == ""
