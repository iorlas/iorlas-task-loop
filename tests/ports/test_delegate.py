"""Delegate: the shared contract on the fake and on RouteDelegate (against stub_route.py, a python script), wire-mapping
checks, the failures only a real process has, and logic tests on the fake."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import support.paths  # noqa: E402,F401
from ports.delegate_contract import SCHEMA, DelegateContract, req  # noqa: E402
from support.tags import contract, domain  # noqa: E402
from taskloop.adapters import delegate_wire  # noqa: E402
from taskloop.adapters.delegate_route import RouteDelegate  # noqa: E402
from taskloop.adapters.fake_delegate import FakeDelegate, Step, done, stopped  # noqa: E402
from taskloop.contracts import codec  # noqa: E402

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


class RouteHarness:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name, "script.json")
        self.addCleanup(self.tmp.cleanup)  # type: ignore[attr-defined]

    def write(self, **script: Any) -> None:
        self.script.write_text(json.dumps(script), encoding="utf-8")

    def route(self, **kw: Any) -> RouteDelegate:
        return RouteDelegate(STUB, env={"STUB_SCRIPT": str(self.script)}, **kw)


@contract
class RouteDelegateContract(RouteHarness, DelegateContract, unittest.TestCase):
    def make(self, *steps: Step) -> RouteDelegate:
        self.write(answer=answer_of(steps[0]), live=[codec.to_json(e) for e in steps[0].events])
        self.steps = steps
        return self.route()

    def seen(self) -> list[dict[str, Any]]:
        rows = [json.loads(x) for x in Path(str(self.script) + ".calls").read_text(encoding="utf-8").splitlines()]
        return [{"role": r["argv"][r["argv"].index("run") + 1], "task": r["argv"][r["argv"].index("--task") + 1],
                 "brief": r["brief"], "schema": r["schema"]} for r in rows]

    def test_steps_play_in_order_and_the_last_repeats(self) -> None:
        self.skipTest("one script per process: sequencing is the fake's feature")


@contract
class RouteDelegateFailures(RouteHarness, unittest.TestCase):
    def stop_of(self, **script: Any) -> Any:
        self.write(**script)
        got = self.route(timeout_s=0.5, backstop_s=0.0).run(req(), "b", SCHEMA)
        assert got.stop is not None, got
        return got

    def test_no_answer_is_a_crash(self) -> None:
        got = self.stop_of(answer=None)
        self.assertEqual((got.status, got.stop.reason, got.stop.permanence), ("error", "crash", "needs_owner"))

    def test_garbage_is_a_crash(self) -> None:
        self.assertEqual(self.stop_of(raw="Traceback ...").stop.reason, "crash")

    def test_an_answer_that_is_not_contract_3_is_a_violation(self) -> None:
        self.assertEqual(self.stop_of(answer={"v": 2, "status": "done"}).stop.reason, "contract_violation")

    def test_a_malformed_stop_is_a_violation(self) -> None:
        self.assertEqual(self.stop_of(answer={"contract": 3, "stop": {"reason": "x", "scope": "galaxy"}}).stop.reason,
                         "contract_violation")

    def test_a_child_past_the_deadline_is_stopped(self) -> None:
        got = self.stop_of(answer=None, sleep=30)
        self.assertEqual((got.status, got.stop.reason), ("timeout", "timeout"))
        self.assertLess(got.secs, 5)

    def test_the_old_contract_is_visible_to_the_gate(self) -> None:
        self.write(contract=2)
        self.assertEqual(self.route().speaks(), 2)

    def test_sandbox_limit_denials_are_not_carried(self) -> None:
        a = answer_of(done(ref="r"))
        a["denied"] = [{"kind": "sandbox_limit", "tool": "ps"}, {"kind": "policy", "tool": "rm", "input": {"a": 1}}]
        self.write(answer=a)
        got = self.route().run(req(), "b", SCHEMA)
        self.assertEqual([(d.tool, d.input) for d in got.denied], [("rm", {"a": 1})])

    def test_usage_tokens_fold_fresh_and_cached_input(self) -> None:
        a = answer_of(done(ref="r"))
        a["usage"]["tokens"] = {"in_fresh": 10, "cache_read": 90, "cache_write": None, "out": 5}
        self.write(answer=a)
        got = self.route().run(req(), "b", SCHEMA)
        assert got.usage is not None and got.usage.tokens is not None
        self.assertEqual((got.usage.tokens.in_, got.usage.tokens.cached, got.usage.tokens.out), (100, 90, 5))

    def test_an_unknown_live_line_is_passed_over(self) -> None:
        self.write(answer=answer_of(done(ref="r")), live=[{"v": 1, "kind": "from_the_future", "t": 1.0}])
        seen: list[Any] = []
        self.assertEqual(self.route().run(req(), "b", SCHEMA, seen.append).status, "done")
        self.assertEqual(seen, [])


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
                self.assertEqual(stopped(reason, scope).result.status, want)

    def test_calls_are_recorded(self) -> None:
        d = FakeDelegate()
        d.run(req(role="plan"), "the brief", SCHEMA)
        self.assertEqual([(c.req.role, c.brief) for c in d.calls], [("plan", "the brief")])

    def test_the_wire_mapper_rejects_a_status_answer(self) -> None:
        self.assertEqual(delegate_wire.result_of({"v": 2, "status": "done"}).stop.reason, "contract_violation")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
