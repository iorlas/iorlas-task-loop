"""Delegate: the shared contract on the fake and on RouteDelegate (against stub_route.py, a python script), wire-mapping
checks, the failures only a real process has, and logic tests on the fake."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_delegate import FakeDelegate, Step, done, stopped
from support.procsim import real_proc
from support.tags import contract, domain

from ports import stub_route
from ports.delegate_contract import SCHEMA, DelegateContract, req
from taskloop.adapters import delegate_route, delegate_wire
from taskloop.adapters.delegate_route import RouteDelegate
from taskloop.adapters.delegate_wire import answer_status
from taskloop.adapters.procs import Ran
from taskloop.contracts import wire
from taskloop.contracts.delegate import LiveCmdStart, LiveEnd, LiveMsg
from taskloop.contracts.env import snapshot

STUB = str(Path(__file__).parent / "stub_route.py")


def answer_of(step: Step) -> dict[str, Any]:
    """A step as delegate's contract-3 wire."""
    r = step.result
    st = r.stop
    stop = None if st is None else {"reason": st.reason, "scope": st.scope, "permanence": st.permanence,
                                    "retry": {"kind": st.retry.kind, "at": st.retry.at}, "ref": st.ref,
                                    "resumable": st.resumable, "partial": st.partial}
    return {"contract": 3, "data": r.data, "text": r.text, "say": r.say, "ref": r.ref, "lane": r.lane, "model": r.model,
            "tokens": None, "cost": 0, "secs": 0.1, "run_id": "stub", "call_id": None, "transcript": None, "denied": [],
            "git_violation": [], "usage": {"tokens": None, "cost": 0, "secs": 0.1, "turns": 1, "context_k": None, "answer_bytes": 0},
            "stop": stop}


@contract
class FakeDelegateContract(DelegateContract, unittest.TestCase):
    def make(self, *steps: Step) -> FakeDelegate:
        self.fake = FakeDelegate(*steps)
        return self.fake

    def seen(self) -> list[dict[str, Any]]:
        return [{"role": c.req.role, "task": c.req.task, "brief": c.brief, "schema": c.schema} for c in self.fake.calls]


def stub_in_process(argv: list[str], cwd: str | None, env: Mapping[str, str] | None, timeout_s: float, tick: Any = None) -> Ran:
    """procs.capture for RouteDelegate with stub_route.main(argv) run in this process (argv is `python route.py ...`); the live file
    is drained once the call ends, as capture's tick does after the child."""
    out = io.StringIO()
    with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out):
        code = stub_route.main(list(argv[2:]))
    if tick:
        tick()
    return Ran(code, out.getvalue(), "", 0.0, False)


class RouteHarness:
    IN_PROCESS = True  # the stub runs in this process; a class that sets False starts it as route.py is started

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name, "script.json")
        self.addCleanup(self.tmp.cleanup)  # type: ignore[attr-defined]
        if self.IN_PROCESS:
            p = mock.patch.object(delegate_route, "run_group", stub_in_process)
            p.start()
            self.addCleanup(p.stop)  # type: ignore[attr-defined]

    def write(self, **script: Any) -> None:
        self.script.write_text(json.dumps(script), encoding="utf-8")

    def route(self, **kw: Any) -> RouteDelegate:
        return RouteDelegate(STUB, snapshot(), env={"STUB_SCRIPT": str(self.script)}, **kw)

    def make(self, *steps: Step) -> RouteDelegate:
        self.write(answer=answer_of(steps[0]), live=[wire_line(e) for e in steps[0].events])
        return self.route()


@contract
class RouteDelegateContract(RouteHarness, DelegateContract, unittest.TestCase):
    def seen(self) -> list[dict[str, Any]]:
        rows = [json.loads(x) for x in Path(str(self.script) + ".calls").read_text(encoding="utf-8").splitlines()]
        return [{"role": r["argv"][r["argv"].index("run") + 1], "task": r["argv"][r["argv"].index("--task") + 1],
                 "brief": r["brief"], "schema": r["schema"]} for r in rows]

    def test_steps_play_in_order_and_the_last_repeats(self) -> None:
        self.skipTest("one script per process: sequencing is the fake's feature")


@contract
@real_proc("argv and stdout through a real pipe, the live file tailed while the child runs, the engine's stop of a child past its deadline")
class RouteDelegateProcess(RouteHarness, unittest.TestCase):
    """Real processes: what only a child has (argv and stdout through a pipe, the live file tailed while it runs, the engine's stop)."""
    IN_PROCESS = False

    def test_live_events_arrive_in_order_before_the_result(self) -> None:
        events = (LiveCmdStart(t=1.0, id="c1", text="ls"), LiveMsg(t=2.0, text="hi"), LiveEnd(t=3.0, status="done", secs=2.0))
        seen: list[Any] = []
        self.make(done(None, "ok", *events, ref="r")).run(req(), "b", SCHEMA, seen.append)
        self.assertEqual(seen, list(events))

    def test_a_child_past_the_deadline_is_stopped(self) -> None:
        self.write(answer=None, sleep=30)
        got = self.route(timeout_s=0.5, backstop_s=0.0).run(req(), "b", SCHEMA)
        assert got.stop is not None, got
        self.assertEqual((answer_status(got), got.stop.reason), ("timeout", "timeout"))
        self.assertLess(got.secs, 5)


@contract
class RouteDelegateFailures(RouteHarness, unittest.TestCase):
    def stop_of(self, **script: Any) -> Any:
        self.write(**script)
        got = self.route(timeout_s=0.5, backstop_s=0.0).run(req(), "b", SCHEMA)
        assert got.stop is not None, got
        return got

    def test_no_answer_is_a_crash(self) -> None:
        got = self.stop_of(answer=None)
        self.assertEqual((answer_status(got), got.stop.reason, got.stop.permanence), ("error", "crash", "needs_owner"))

    def test_garbage_is_a_crash(self) -> None:
        self.assertEqual(self.stop_of(raw="Traceback ...").stop.reason, "crash")

    def test_an_answer_that_is_not_contract_3_is_a_violation(self) -> None:
        self.assertEqual(self.stop_of(answer={"v": 2, "status": "done"}).stop.reason, "contract_violation")

    def test_a_malformed_stop_is_a_violation(self) -> None:
        self.assertEqual(self.stop_of(answer={"contract": 3, "stop": {"reason": "x", "scope": "galaxy"}}).stop.reason,
                         "contract_violation")

    def test_the_old_contract_is_visible_to_the_gate(self) -> None:
        self.write(contract=2)
        self.assertEqual(self.route().speaks(), 2)

    def test_sandbox_limit_denials_are_not_carried(self) -> None:
        a = answer_of(done(ref="r"))
        a["denied"] = [{"kind": "sandbox_limit", "tool": "ps"}, {"kind": "policy", "tool": "rm", "input": {"a": 1}}]
        self.write(answer=a)
        got = self.route().run(req(), "b", SCHEMA)
        self.assertEqual([(d.kind, d.tool, d.input) for d in got.denied], [("policy", "rm", {"a": 1})])

    def test_usage_tokens_keep_fresh_and_cached_input_apart(self) -> None:
        a = answer_of(done(ref="r"))
        a["usage"]["tokens"] = {"in_fresh": 10, "cache_read": 90, "cache_write": None, "out": 5}
        self.write(answer=a)
        got = self.route().run(req(), "b", SCHEMA)
        assert got.usage is not None and got.usage.tokens is not None
        self.assertEqual((got.usage.tokens.in_fresh, got.usage.tokens.cache_read, got.usage.tokens.cache_write, got.usage.tokens.out),
                         (10, 90, None, 5))

    def test_an_unknown_live_line_is_passed_over(self) -> None:
        self.write(answer=answer_of(done(ref="r")), live=[{"k": "from_the_future", "t": 1.0}])
        seen: list[Any] = []
        self.assertEqual(answer_status(self.route().run(req(), "b", SCHEMA, seen.append)), "done")
        self.assertEqual(seen, [])


def wire_line(event: Any) -> dict[str, Any]:
    """One live-file line as delegate writes it: `k` names the kind, and there is no `v`."""
    j = wire.dump(event)
    j.pop("v", None)
    return {"k": j.pop("kind"), **j}


@domain
class FakeDelegateLogic(unittest.TestCase):
    def test_resume_is_echoed_as_the_ref(self) -> None:
        d = FakeDelegate(done())
        self.assertEqual(d.run(req(resume="s-9"), "b", SCHEMA).ref, "s-9")
        self.assertEqual(d.run(req(), "b", SCHEMA).ref, "fake-2")

    def test_the_wire_status_table(self) -> None:
        cases = [("timeout", "bead", "timeout"), ("worker_failed", "bead", "failed"), ("bad_request", "caller", "error"),
                 ("busy", "lane", "lane_out"), ("network", "machine", "stop")]
        for reason, scope, want in cases:
            with self.subTest(reason):
                self.assertEqual(answer_status(stopped(reason, scope).result), want)

    def test_calls_are_recorded(self) -> None:
        d = FakeDelegate()
        d.run(req(role="plan"), "the brief", SCHEMA)
        self.assertEqual([(c.req.role, c.brief) for c in d.calls], [("plan", "the brief")])

    def test_the_wire_mapper_rejects_a_status_answer(self) -> None:
        self.assertEqual(delegate_wire.result_of({"v": 2, "status": "done"}).stop.reason, "contract_violation")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
