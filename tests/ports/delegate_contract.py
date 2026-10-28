"""The Delegate contract, one suite for every implementation. A subclass sets `make(*steps) -> Delegate` scripted with the
steps (fake_delegate.Step) and `calls() -> [(argv-free request facts)]`, and gets every test below."""
from typing import Any

from taskloop.adapters.delegate_wire import answer_next, answer_status
from taskloop.adapters.fake_delegate import done, stopped
from taskloop.contracts.delegate import LiveCmdStart, LiveEnd, LiveMsg, RunRequest
from taskloop.contracts.ports import Delegate

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}}


def req(**kw: Any) -> RunRequest:
    base: dict[str, Any] = {"role": "writer", "brief_path": "", "schema_path": "", "cwd": ".", "task": "b-1", "title": "t", "parent": "b-0"}
    return RunRequest(**{**base, **kw})


class DelegateContract:
    def make(self, *steps: Any) -> Delegate:
        raise NotImplementedError

    def seen(self) -> list[dict[str, Any]]:
        """What the delegate was asked, per call: role, task, brief, schema."""
        raise NotImplementedError

    def test_it_speaks_contract_3(self) -> None:
        self.assertEqual(self.make(done(ref="r")).speaks(), 3)  # type: ignore[attr-defined]

    def test_done_carries_the_answer(self) -> None:
        d = self.make(done({"x": 1}, "all good", ref="r-1"))
        got = d.run(req(), "do it", SCHEMA)
        self.assertEqual((answer_status(got), got.data, got.text, got.ref, got.stop), ("done", {"x": 1}, "all good", "r-1", None))  # type: ignore[attr-defined]

    def test_the_request_reaches_the_delegate_as_values(self) -> None:
        self.make(done(ref="r")).run(req(role="reviewer", task="b-9"), "the brief", SCHEMA)
        self.assertEqual([(c["role"], c["task"], c["brief"], c["schema"]) for c in self.seen()],  # type: ignore[attr-defined]
                         [("reviewer", "b-9", "the brief", SCHEMA)])

    def test_a_transient_stop_keeps_its_facts(self) -> None:
        d = self.make(stopped("network", "machine", "transient", "poll", None, ref="s-1", resumable=True, partial=True))
        got = d.run(req(), "b", SCHEMA)
        st = got.stop
        assert st is not None
        self.assertEqual((st.reason, st.scope, st.permanence, st.retry.kind, st.retry.at, st.resumable, st.partial),  # type: ignore[attr-defined]
                         ("network", "machine", "transient", "poll", None, True, True))
        self.assertEqual((answer_status(got), answer_next(got)), ("stop", "retry"))  # type: ignore[attr-defined]

    def test_a_lane_limit_predicts_its_end(self) -> None:
        got = self.make(stopped("rate_limited", "lane", "transient", "predicted", 1800000000.0, ref="r")).run(req(), "b", SCHEMA)
        assert got.stop is not None
        self.assertEqual((answer_status(got), got.stop.retry.kind, got.stop.retry.at), ("lane_out", "predicted", 1800000000.0))  # type: ignore[attr-defined]

    def test_an_owner_stop_says_owner(self) -> None:
        got = self.make(stopped("secrets", "bead", "needs_owner", ref="r")).run(req(), "b", SCHEMA)
        self.assertEqual((answer_status(got), answer_next(got)), ("failed", "owner"))  # type: ignore[attr-defined]

    def test_live_events_arrive_in_order_before_the_result(self) -> None:
        events = (LiveCmdStart(t=1.0, id="c1", text="ls"), LiveMsg(t=2.0, text="hi"), LiveEnd(t=3.0, status="done", secs=2.0))
        seen: list[Any] = []
        self.make(done(None, "ok", *events, ref="r")).run(req(), "b", SCHEMA, seen.append)
        self.assertEqual(seen, list(events))  # type: ignore[attr-defined]

    def test_steps_play_in_order_and_the_last_repeats(self) -> None:
        d = self.make(stopped("busy", "lane", "transient", "poll", ref="r"), done(ref="r"))
        statuses = [answer_status(d.run(req(), "b", SCHEMA)) for _ in range(3)]
        self.assertEqual(statuses, ["lane_out", "done", "done"])  # type: ignore[attr-defined]
