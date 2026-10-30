"""Resource classes (tl-7k8.5): `needs: [unity]` takes a machine-wide lease (at most `limit` at once, the wait recorded per check); a
host without the resource defers the check, and the land goes on past it only when the diff did not touch what the check reads."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest
from support.logs import records

# isort: split
from taskloop.app.checks import resources
from taskloop.app.checks.resources import Resources
from taskloop.app.land import verified
from taskloop.app.plan.planner import Planner
from taskloop.contracts.checks import UNVERIFIED_EXIT, Check, CheckResult, CheckRun
from taskloop.contracts.config import ConfigError, EngineConfig, HostResources, ResourceSpec, load
from taskloop.contracts.enums import LockWhat, WaitWhat
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.inputs import touched
from taskloop.stores.memory import fake_stores

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
UNITY = {"unity": {"limit": 1}}


class FakeWaits:
    def __init__(self) -> None:
        self.rows: list[tuple[str, WaitWhat, float | None]] = []

    def start(self, what, holder="", until=None):
        self.rows.append(("start", what, None))
        return "w1"

    def add(self, secs, what, wid=None):
        self.rows.append(("add", what, secs))


class FakeHost:
    bead = "t-1"

    def __init__(self, limit: int) -> None:
        self.cfg = EngineConfig(resources={"unity": ResourceSpec(limit=limit)})
        self.stores = fake_stores()
        self.fake_waits = FakeWaits()
        self.waits = self.fake_waits

    def warn(self, text): ...
    def halt_point(self, when=True, wait=0): ...


def unity_check(id="u") -> Check:
    return Check(id=CheckId(id), cmd=id, needs=["unity"])


class Lease(unittest.TestCase):
    def run_checks(self, limit: int, n: int) -> tuple[int, list[float]]:
        """n threads each run a check that needs unity for 0.15 s: -> the most that ran at once, and each one's wait."""
        host = FakeHost(limit)
        res = Resources(host, sleep=lambda s: time.sleep(0.01))
        now, top, lock, waited = [0], [0], threading.Lock(), []

        def one(i):
            with res.hold(unity_check(f"u{i}")) as lease:
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
        self.assertEqual(top, 1)
        self.assertEqual(sum(1 for w in waited if w > 0.1), 2)  # two of the three queued behind another

    def test_a_limit_of_two_runs_two(self):
        top, _ = self.run_checks(2, 4)
        self.assertEqual(top, 2)

    def test_the_wait_is_booked_as_a_resource_wait(self):
        self.run_checks(1, 2)
        kinds = [(k, w) for k, w, _ in self.host.fake_waits.rows]
        self.assertEqual(kinds, [("start", WaitWhat.RESOURCE), ("add", WaitWhat.RESOURCE)])
        self.assertGreater(self.host.fake_waits.rows[1][2] or 0, 0.1)

    def test_a_check_without_needs_takes_no_lease(self):
        host = FakeHost(1)
        with Resources(host).hold(Check(id=CheckId("x"), cmd="x")) as lease:
            self.assertEqual(host.stores.locks.holder(LockWhat.RESOURCE, "unity-0"), None)
        self.assertEqual(lease.waited, 0.0)

    def test_the_lease_is_the_machine_lock_table_and_is_freed_after_the_block(self):
        host = FakeHost(1)
        with Resources(host).hold(unity_check()):
            self.assertIsNotNone(host.stores.locks.holder(LockWhat.RESOURCE, "unity-0"))
        self.assertIsNone(host.stores.locks.holder(LockWhat.RESOURCE, "unity-0"))


class Host(unittest.TestCase):
    def test_no_host_file_means_the_host_has_every_declared_resource(self):
        host = FakeHost(1)
        self.assertEqual(Resources(host).lacking(unity_check()), [])

    def test_a_host_file_names_what_the_host_has(self):
        host = FakeHost(1)
        host.stores.host.write(HostResources(resources=[]))
        self.assertEqual(Resources(host).lacking(unity_check()), ["unity"])
        host.stores.host.write(HostResources(resources=["unity"]))
        self.assertEqual(Resources(host).lacking(unity_check()), [])

    def test_a_check_needing_an_undeclared_resource_is_refused_at_load(self):
        with self.assertRaises(ConfigError) as cm:
            load({"engine": {"checks": [{"id": "u", "argv": ["true"], "needs": ["unity"]}]}})
        self.assertIn("engine.resources does not declare", str(cm.exception))
        ok = load({"engine": {"resources": UNITY, "checks": [{"id": "u", "argv": ["true"], "needs": ["unity"]}]}})
        self.assertEqual(ok.engine.checks[0].needs, ["unity"])

    def test_an_unknown_key_in_a_resource_is_refused(self):
        with self.assertRaises(ConfigError):
            load({"engine": {"resources": {"unity": {"limit": 1, "slots": 2}}}})
        with self.assertRaises(ConfigError):
            load({"engine": {"resources": {"unity": {"limit": 0}}}})


class Touched(unittest.TestCase):
    def test_a_diff_touches_a_check_by_its_inputs(self):
        c = Check(id=CheckId("u"), cmd="u", inputs=["client/**"], inputs_only=True)
        self.assertTrue(touched(c, ["client/a.cs"]))
        self.assertFalse(touched(c, ["docs/a.md", "justfile"]))
        self.assertTrue(touched(c.replace(inputs_only=False), ["justfile"]))  # the cache key reads the justfile too
        self.assertTrue(touched(Check(id=CheckId("w"), cmd="w"), ["docs/a.md"]))  # no inputs: the whole tree
        self.assertFalse(touched(Check(id=CheckId("w"), cmd="w"), []))


class Deferral(unittest.TestCase):
    def deferred(self, changed: bool) -> CheckResult:
        return CheckResult(id=CheckId("u"), cmd="u", group="tests", exit=UNVERIFIED_EXIT, status="unverified", deferred=["unity"],
                           inputs_changed=changed)

    def test_a_deferred_check_with_unchanged_inputs_is_passed_over_and_named(self):
        run = CheckRun(round=1, results=[self.deferred(False)])
        self.assertEqual((verified.refusal(run), verified.passed_over(run)), ("", ["u"]))

    def test_a_deferred_check_with_changed_inputs_waits_for_a_host_with_the_resource(self):
        run = CheckRun(round=1, results=[self.deferred(True)])
        self.assertEqual(verified.kind_of(run), "PAUSE_MOVED")
        self.assertIn("labelled needs:unity", verified.refusal(run))
        self.assertEqual(verified.moves(run), ["unity"])

    def test_another_unverified_check_keeps_the_land_a_fault(self):
        other = CheckResult(id=CheckId("r"), cmd="r", group="tests", exit=UNVERIFIED_EXIT, status="unverified")
        self.assertEqual(verified.kind_of(CheckRun(round=1, results=[self.deferred(True), other])), "FAULT_LAND")


class Engine(EngineTest):
    def lacking(self, eng):
        eng.stores.host.write(HostResources(resources=[]))

    def checks(self, inputs, cmd="true"):
        return [{"id": "ut", "cmd": cmd, "run": "both", "inputs": inputs, "needs": ["unity"]}]

    def test_the_wait_for_the_lease_is_recorded_on_the_check_result_and_its_end_row(self):
        gate, polled = threading.Event(), threading.Event()  # the holder has the lease; the check polled and found it taken
        real_init = Resources.__init__

        def init(res, host, sleep=time.sleep):
            real_init(res, host, sleep)
            res.sleep = lambda s: (polled.set(), sleep(s))[1]  # the check's first wait is its first poll that lost

        def hold_it(eng):
            def hold():
                with eng.stores.locks.hold(LockWhat.RESOURCE, "unity-0", "another slot"):
                    gate.set()
                    polled.wait(30)  # freed only after the check lost a poll, however slow the engine start is
                    time.sleep(0.25)  # a fixed hold after that: the check waits at least this long

            threading.Thread(target=hold, daemon=True).start()
            gate.wait(5)

        with mock.patch.object(resources, "POLL_S", 0.02), mock.patch.object(Resources, "__init__", init):
            rc, _ = self.run_engine(ANSWERS, prep=hold_it, resources=UNITY, checks=self.checks(["f.txt"]))
        self.assertEqual(rc, 0, self.blocked)
        waits = sorted(r["waited"] for r in records(self.eng, "check_end"))
        self.assertGreaterEqual(waits[-1], 0.2, waits)  # the unity check queued behind the other slot's lease
        self.assertEqual(waits[:-1], [0.0] * (len(waits) - 1))  # and no other check waited

    def test_a_host_without_the_resource_lands_when_the_diff_leaves_the_inputs_alone(self):
        rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=self.checks(["client/**"]))
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(records(self.eng, "gate_end")[-1]["deferred"], ["ut"])
        notes = " ".join(str(r.get("text", "")) for r in records(self.eng, "note"))
        self.assertIn("deferred checks", notes)
        self.assertIn("ut", notes)

    def test_a_plan_that_touches_the_inputs_moves_the_bead_before_any_code_is_written(self):
        rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=self.checks(["f.txt"]))
        self.assertNotEqual(rc, 0)
        r = self.eng.result()
        self.assertEqual((r.outcome, r.kind), ("paused", "pause_moved"))
        self.assertIn("labelled needs:unity", r.why)
        self.assertEqual(self.store.said("label", "add"), [("label", "add", "t-1", "needs:unity")])
        self.assertEqual(records(self.eng, "gate_end"), [])

    def test_a_diff_that_hits_the_inputs_the_plan_did_not_name_moves_the_bead_at_the_land(self):
        with mock.patch.object(Planner, "move_if_lacking"):  # the plan did not see it: the land is the second look
            rc, _ = self.run_engine(ANSWERS, prep=self.lacking, resources=UNITY, checks=[dict(self.checks(["f.txt"])[0], run="gate")])
        self.assertNotEqual(rc, 0)
        r = self.eng.result()
        self.assertEqual((r.outcome, r.kind), ("paused", "pause_moved"))
        self.assertEqual(self.store.said("label", "add"), [("label", "add", "t-1", "needs:unity")])
        self.assertEqual(self.store.said("close"), [])
        self.assertEqual([g["exit"] for g in records(self.eng, "gate_end")], [1])  # it got as far as the land's gate

    def test_a_host_that_has_the_resource_adds_no_label_and_lands(self):
        rc, _ = self.run_engine(ANSWERS, resources=UNITY, checks=self.checks(["f.txt"]))
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.store.said("label", "add"), [])


if __name__ == "__main__":
    unittest.main()
