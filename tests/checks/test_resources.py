"""Resource classes (tl-7k8.5): `needs: [unity]` takes a machine-wide lease (at most `limit` at once, the wait recorded per check); a
host without the resource defers the check, and the land goes on past it only when the diff did not touch what the check reads."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.plans import CLEAN, PLAN, WRITE
from support.procsim import real_proc

# isort: split
from any_lease import Leases
from support.memstores import fake_stores

from taskloop.app.land import verified
from taskloop.app.wire.brief import held_resources
from tlgate import resources
from tlgate.domain.inputs import touched
from tlgate.resources import Resources
from tlkernel.checks import UNVERIFIED_EXIT, Check, CheckResult, CheckRun
from tlkernel.config import ConfigError, EngineConfig, HostResources, ResourceSpec, load
from tlkernel.ids import CheckId
from tlkernel.paths import ConfigDir
from tlkernel.waitenums import WaitWhat

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
UNITY = {"unity": {"limit": 1}}


class FakeWaits:
    def __init__(self) -> None:
        self.rows: list[tuple] = []

    def start(self, what, holder="", until=None, lane="", check=""):
        self.rows.append(("start", what, holder, lane, check))
        return "w1"

    def add(self, secs, what, wid=None, lane="", check=""):
        self.rows.append(("add", what, secs, lane, check))


class FakeHost:
    bead = "t-1"

    def __init__(self, limit: int) -> None:
        self.cfg = EngineConfig(resources={"unity": ResourceSpec(limit=limit)})
        self.stores = fake_stores()
        self.fake_waits = FakeWaits()
        self.waits = self.fake_waits

    def warn(self, text): ...
    def halt_point(self, when=True, wait=0): ...


def unity_check(id="u", lane="") -> Check:
    return Check(id=CheckId(id), cmd=id, needs=["unity"], lane=lane)


def python(code: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", code, *args], stdout=subprocess.PIPE, text=True)


HOLD = ("import sys, time; from pathlib import Path; from any_lease import Leases\n"
        "h = Leases(Path(sys.argv[1])).acquire('unity', 1, label='other:proc'); print('held', flush=True); time.sleep(60)")


class Lease(Case):
    def setup_method(self) -> None:
        patcher = mock.patch.object(resources, "POLL_S", 0.02)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_checks(self, limit: int, n: int) -> tuple[int, list[float]]:
        """n threads each run a check that needs unity for 0.15 s: -> the most that ran at once, and each one's wait."""
        host = FakeHost(limit)
        res = Resources(host)
        now, top, lock, waited = [0], [0], threading.Lock(), []

        def one(i):
            with res.hold(unity_check(f"u{i}", lane=f"l{i}")) as lease:
                with lock:
                    now[0] += 1
                    top[0] = max(top[0], now[0])
                time.sleep(0.15)
                with lock:
                    now[0] -= 1
            waited.append(lease.waited)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.host = host
        return top[0], waited

    def test_a_limit_of_one_runs_one_such_check_at_a_time(self):
        top, waited = self.run_checks(1, 3)
        assert top == 1
        assert sum(1 for w in waited if w > 0.1) == 2  # two of the three queued behind another

    def test_a_limit_of_two_runs_two(self):
        top, _ = self.run_checks(2, 4)
        assert top == 2

    def test_the_wait_is_booked_as_a_resource_wait(self):
        self.run_checks(1, 2)
        kinds = [(r[0], r[1]) for r in self.host.fake_waits.rows]
        assert kinds == [("start", WaitWhat.RESOURCE), ("add", WaitWhat.RESOURCE)]
        assert self.host.fake_waits.rows[1][2] > 0.1

    def test_the_wait_names_the_waiting_check_its_lane_and_the_holder(self):
        host, first = FakeHost(1), threading.Event()
        res = Resources(host)

        def holder():
            with res.hold(unity_check("first", lane="a")):
                first.set()
                time.sleep(0.2)

        t = threading.Thread(target=holder)
        t.start()
        first.wait(5)
        with res.hold(unity_check("second", lane="b")):
            pass
        t.join()
        start, add = host.fake_waits.rows
        assert start[2:] == ("t-1:first", "b", "second")  # holder bead:check, waiting lane and check
        assert (add[3], add[4]) == ("b", "second")

    def test_status_reads_the_holder_bead_and_check_from_the_lease_label(self):
        host = FakeHost(1)
        cfg = ConfigDir(host.stores.leases.root.parent / "cfg")
        with Leases(cfg.leases()).acquire("unity", 1, label="t-9:unity-tests"):
            assert [(r.name, r.bead, r.check) for r in held_resources(cfg)] == [("unity", "t-9", "unity-tests")]
        assert held_resources(cfg) == ()

    def test_a_check_without_needs_takes_no_lease(self):
        host = FakeHost(1)
        with Resources(host).hold(Check(id=CheckId("x"), cmd="x")) as lease:
            assert list(host.stores.leases.root.glob("*")) == []
        assert lease.waited == 0.0

    def test_the_lease_is_the_machine_table_and_is_freed_after_the_block(self):
        host = FakeHost(1)
        with Resources(host).hold(unity_check("u", lane="a")) as lease:
            (occ,) = host.stores.leases.holders("unity", 1)
            assert occ.holder is not None
            assert occ.holder.created == pytest.approx(time.time(), abs=5)  # `tl status` counts the seconds held from it
            assert (occ.holder.label, occ.holder.meta["lane"]) == ("t-1:u", "a")
            assert lease.env == {"ANY_LEASE_HELD": "unity", "ANY_LEASE_ROOT": str(host.stores.leases.root)}
        assert host.stores.leases.holders("unity", 1) == ()

    @real_proc("a SIGKILLed process must give its unit back: the kernel frees the flock")
    def test_a_killed_holder_releases_its_lease(self):
        host = FakeHost(1)
        proc = python(HOLD, str(host.stores.leases.root))
        self.addCleanup(proc.kill)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "held"  # a real process has the only unit
        assert len(host.stores.leases.holders("unity", 1)) == 1
        proc.kill()
        proc.wait(10)
        with Resources(host).hold(unity_check()) as lease:  # the kernel dropped its flock: no stale lease
            assert lease.waited < 5

    @real_proc("a real `python -m any_lease run` queues behind the engine on the same table")
    def test_a_manual_run_and_the_engine_share_one_lease(self):
        host = FakeHost(1)
        root = str(host.stores.leases.root)
        run = [sys.executable, "-m", "any_lease", "run", "--root", root, "--poll", "0.05", "unity", "1", "manual", "--", "true"]
        with Resources(host).hold(unity_check()) as lease:
            manual = subprocess.Popen(run, stderr=subprocess.PIPE, text=True)
            self.addCleanup(manual.kill)
            time.sleep(1)
            assert manual.poll() is None  # queues behind the engine's lease
            nested = subprocess.run(run, env={**os.environ, **lease.env}, timeout=10, check=False)  # inside the check's command: just runs
            assert nested.returncode == 0
        assert manual.wait(10) == 0
        assert manual.stderr is not None
        assert "t-1:u" in manual.stderr.read()  # it told who it waited for

    def test_a_changed_profile_limit_replaces_the_declared_one_while_idle_and_is_refused_while_held(self):
        host = FakeHost(1)
        with Resources(host).hold(unity_check()):
            pass
        host.cfg = EngineConfig(resources={"unity": ResourceSpec(limit=2)})
        with Resources(host).hold(unity_check()):
            assert host.stores.leases.declare("unity") == 2
            host.cfg = EngineConfig(resources={"unity": ResourceSpec(limit=3)})
            with pytest.raises(ValueError), Resources(host).hold(unity_check("v")):
                pass


class Host(Case):
    def test_no_host_file_means_the_host_has_every_declared_resource(self):
        host = FakeHost(1)
        assert Resources(host).lacking(unity_check()) == []

    def test_a_host_file_names_what_the_host_has(self):
        host = FakeHost(1)
        host.stores.host.write(HostResources(resources=[]))
        assert Resources(host).lacking(unity_check()) == ["unity"]
        host.stores.host.write(HostResources(resources=["unity"]))
        assert Resources(host).lacking(unity_check()) == []

    def test_a_check_needing_an_undeclared_resource_is_refused_at_load(self):
        with pytest.raises(ConfigError) as cm:
            load({"engine": {"checks": [{"id": "u", "argv": ["true"], "needs": ["unity"]}]}})
        assert "engine.resources does not declare" in str(cm.value)
        ok = load({"engine": {"resources": UNITY, "checks": [{"id": "u", "argv": ["true"], "needs": ["unity"]}]}})
        assert ok.engine.checks[0].needs == ["unity"]

    def test_an_unknown_key_in_a_resource_is_refused(self):
        with pytest.raises(ConfigError):
            load({"engine": {"resources": {"unity": {"limit": 1, "slots": 2}}}})
        with pytest.raises(ConfigError):
            load({"engine": {"resources": {"unity": {"limit": 0}}}})


class Touched(Case):
    def test_a_diff_touches_a_check_by_its_inputs(self):
        c = Check(id=CheckId("u"), cmd="u", inputs=["client/**"], inputs_only=True)
        assert touched(c, ["client/a.cs"])
        assert not touched(c, ["docs/a.md", "justfile"])
        assert touched(c.replace(inputs_only=False), ["justfile"])  # the cache key reads the justfile too
        assert touched(Check(id=CheckId("w"), cmd="w"), ["docs/a.md"])  # no inputs: the whole tree
        assert not touched(Check(id=CheckId("w"), cmd="w"), [])


class Deferral(Case):
    def deferred(self, changed: bool) -> CheckResult:
        return CheckResult(id=CheckId("u"), cmd="u", group="tests", exit=UNVERIFIED_EXIT, status="unverified", deferred=["unity"],
                           inputs_changed=changed)

    def test_a_deferred_check_with_unchanged_inputs_is_passed_over_and_named(self):
        run = CheckRun(round=1, results=[self.deferred(False)])
        assert (verified.refusal(run), verified.passed_over(run)) == ("", ["u"])

    def test_a_deferred_check_with_changed_inputs_waits_for_a_host_with_the_resource(self):
        run = CheckRun(round=1, results=[self.deferred(True)])
        assert verified.kind_of(run) == "PAUSE_MOVED"
        assert "labelled needs:unity" in verified.refusal(run)
        assert verified.moves(run) == ["unity"]

    def test_another_unverified_check_keeps_the_land_a_fault(self):
        other = CheckResult(id=CheckId("r"), cmd="r", group="tests", exit=UNVERIFIED_EXIT, status="unverified")
        assert verified.kind_of(CheckRun(round=1, results=[self.deferred(True), other])) == "FAULT_LAND"
