"""Thread selection and fresh recovery keep prompts and charges inside delegate."""

from dataclasses import replace
from pathlib import Path

import pytest

from delegate import api
from delegate.app import answer, env, threads
from delegate.contracts import codec, schema, wire
from delegate.contracts.json_types import obj
from delegate.contracts.state import StateDoc, ThreadRecord, V, split_retired_state
from delegate.contracts.wire import Attempt, Retry, RunRequest, RunResult, StopFacts, Tokens, UsageTokens
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


def result(reason=None, ref="session", **kw):
    return codec.from_json(RunResult, answer.result(reason, ref=ref, lane="L", model="M", **kw))


class TestThreads(Case):
    def setup_method(self):
        tmp = self.enterContext(TemporaryDirectory())
        self.whole, self.delta = Path(tmp) / "whole", Path(tmp) / "delta"
        self.whole.write_text("whole")
        self.delta.write_text("delta")
        self.request = RunRequest(role="worker", task="bead", thread="write", brief_file=str(self.whole), cwd=tmp)

    @pytest.mark.parametrize("thread,record,delta,expected", [
        ("", False, False, ("", "caller-ref", "whole", False)),
        ("write", False, True, ("bead/write", None, "whole", False)),
        ("write", True, True, ("bead/write", "session", "delta", False)),
        ("write", True, False, ("bead/write", None, "whole" + threads.TAKEOVER_NOTE, True)),
    ])
    def test_plan(self, thread, record, delta, expected):
        state = StateDoc()
        if record:
            threads.settle(state, "bead/write", result())
        request = replace(self.request, thread=thread, resume="caller-ref", delta_file=str(self.delta) if delta else None)
        plan = threads.plan(request, state)
        assert (plan.key, plan.resume, plan.brief_text, plan.takeover) == expected

    def test_task_namespaces_the_thread(self):
        state = StateDoc(threads={"other/write": ThreadRecord(ref="other", lane="L", model="M")})
        assert threads.plan(replace(self.request, delta_file=str(self.delta)), state).resume is None

    def test_api_stores_then_resumes_delta(self, monkeypatch):
        calls = self.fake_calls(monkeypatch, [result(ref="first"), result(ref="second")])
        assert api.run(self.request).ref == "first"
        assert env.load_state().threads["bead/write"].ref == "first"
        assert api.run(replace(self.request, delta_file=str(self.delta))).ref == "second"
        assert calls == [(None, "whole"), ("first", "delta")]
        assert env.load_state().threads["bead/write"].ref == "second"

    @pytest.mark.parametrize("reason", ["held", "busy", "bad_request", "worker_failed", "timeout"])
    def test_api_resumed_stop_gets_one_fresh_thread(self, monkeypatch, reason):
        env.update_state(lambda state: threads.settle(state, "bead/write", result()))
        first = result(reason, retry_after=1000 if reason == "held" else None, cost=2, tokens={"in": 10, "cached": 1, "out": 2}, secs=3)
        last = result(ref="fresh", cost=4, tokens={"in": 20, "cached": 2, "out": 4}, secs=5)
        calls = self.fake_calls(monkeypatch, [first, last], check_drop=True)
        res = api.run(replace(self.request, delta_file=str(self.delta)))
        assert res.stop is None
        assert calls == [("session", "delta"), (None, "whole" + threads.TAKEOVER_NOTE)]
        assert res.tokens is not None
        assert (res.cost, res.secs, res.tokens.in_) == (6, 8, 30)
        assert isinstance(res.attempts, list)
        assert [a.kind for a in res.attempts] == ["first", "new_thread"]
        assert env.load_state().threads["bead/write"].ref == "fresh"

    @pytest.mark.parametrize("reason", [None, "network", "logged_out", "crash", "secrets"])
    def test_api_other_answers_do_not_rerun(self, monkeypatch, reason):
        env.update_state(lambda state: threads.settle(state, "bead/write", result()))
        calls = self.fake_calls(monkeypatch, [result(reason)])
        res = api.run(replace(self.request, delta_file=str(self.delta)))
        assert res.reason == reason
        assert calls == [("session", "delta")]

    def test_api_fresh_stop_does_not_retry(self, monkeypatch):
        calls = self.fake_calls(monkeypatch, [result("held")])
        assert api.run(self.request).reason == "held"
        assert calls == [(None, "whole")]

    def test_api_fresh_recovery_is_only_once(self, monkeypatch):
        env.update_state(lambda state: threads.settle(state, "bead/write", result()))
        calls = self.fake_calls(monkeypatch, [result("busy"), result("busy", ref=None)])
        res = api.run(replace(self.request, delta_file=str(self.delta)))
        assert res.reason == "busy"
        assert len(calls) == 2
        assert "bead/write" not in env.load_state().threads

    def fake_calls(self, monkeypatch, results, check_drop=False):
        calls, replies = [], iter(results)

        class FakeRun:
            def __init__(self, args, cfg, **kw):
                if check_drop and calls:
                    assert "bead/write" not in env.load_state().threads
                calls.append((args.resume, kw["brief"]))

            def call(self):
                return codec.to_json(next(replies))

        monkeypatch.setattr(api.run_app, "Run", FakeRun)
        return calls


@pytest.mark.parametrize("reason", [None, "network", "held", "worker_failed"])
def test_settle_keeps_refs_on_every_outcome(reason):
    state = StateDoc()
    threads.settle(state, "task/write", result(reason))
    assert state.threads == {"task/write": ThreadRecord(ref="session", lane="L", model="M")}
    threads.settle(state, "task/write", result(reason, ref=None))
    assert state.threads["task/write"].ref == "session"
    threads.settle(state, "", result())
    assert len(state.threads) == 1


def test_settle_caps_by_most_recent_update():
    state = StateDoc()
    for i in range(200):
        threads.settle(state, str(i), result(ref=str(i)))
    threads.settle(state, "0", result(ref="updated"))
    threads.settle(state, "new", result())
    assert len(state.threads) == 200
    assert "1" not in state.threads
    assert state.threads["0"].ref == "updated"


def test_thread_state_round_trip_refuses_the_old_version_and_filters_retired_lanes():
    state = StateDoc(threads={"task/write": ThreadRecord(ref="r", lane="L", model="M")})
    data = codec.to_json(state)
    assert codec.from_json(StateDoc, data) == state
    with pytest.raises(codec.StaleRecord):
        codec.from_json(StateDoc, data | {"v": V - 1})
    kept, gone = split_retired_state({"threads": {
        "task/old": {"ref": "old", "lane": "CLAUDE_CREDIT", "model": "M"},
        "task/write": {"ref": "r", "lane": "L", "model": "M"},
    }})
    assert gone == ["threads.task/old"]
    assert list(obj(kept["threads"])) == ["task/write"]


def test_fresh_merge_keeps_usage_accounting_and_existing_attempts():
    first = result("busy", tokens={"in": 10, "cached": 3, "out": 2}, cost=2, secs=3)
    last = result(ref="new", tokens={"in": 20, "cached": 4, "out": 5}, cost=4, secs=6)
    first = replace(first, usage=replace(
        first.usage, tokens=UsageTokens(in_=10, cached=3, out=2, in_fresh=7, cache_read=3, cache_write=1),
        cost=2, secs=3, turns=1, answer_bytes=10,
        cost_usd=0.2, cost_source="harness", accounting="exact",
    ), attempts=[
        Attempt(kind="first", lane="L", model="M", outcome="busy", secs=1, tokens=Tokens(in_=5, cached=1, out=1)),
        Attempt(kind="lane_poll", lane="L", model="M", outcome="busy", secs=2, tokens=Tokens(in_=5, cached=2, out=1)),
    ])
    last = replace(last, usage=replace(
        last.usage, tokens=UsageTokens(in_=20, cached=4, out=5, in_fresh=16, cache_read=4, cache_write=2),
        ref="new", cost=4, secs=6, turns=2, answer_bytes=20,
        cost_usd=0.4, cost_source="harness", accounting="exact",
    ))
    merged = threads.merge(first, last)
    assert (merged.cost, merged.secs) == (6, 9)
    assert (merged.usage.cost, merged.usage.secs, merged.usage.turns, merged.usage.answer_bytes) == (6, 9, 3, 30)
    assert merged.usage.cost_usd == pytest.approx(0.6)
    assert merged.tokens is not None
    assert isinstance(merged.usage.tokens, UsageTokens)
    assert (merged.tokens.in_, merged.usage.tokens.in_) == (30, 30)
    assert merged.usage.ref == "new"
    assert (merged.usage.tokens.in_fresh, merged.usage.tokens.cache_read, merged.usage.tokens.cache_write) == (23, 7, 3)
    assert isinstance(merged.attempts, list)
    assert [a.kind for a in merged.attempts] == ["first", "lane_poll", "new_thread"]


@pytest.mark.parametrize("scope", ["caller", "bead", "lane", "model", "machine"])
@pytest.mark.parametrize("permanence", ["transient", "needs_owner"])
@pytest.mark.parametrize("kind", ["none", "predicted", "poll"])
def test_fresh_recovery_stop_classes(scope, permanence, kind):
    res = replace(result(), stop=StopFacts(
        reason="example", scope=scope, permanence=permanence, retry=Retry(kind=kind, at=None), ref="session",
    ))
    expected = (scope == "caller" and permanence == "needs_owner") or (
        permanence == "transient" and (
            (scope == "bead" and kind in ("none", "predicted"))
            or (scope in ("lane", "model") and kind in ("predicted", "poll"))
        )
    )
    assert threads.needs_fresh(res) is expected


def test_thread_wire_fields_and_capabilities_match_the_published_contract():
    contract = api.contract()
    assert contract["capabilities"] == list(wire.CAPABILITIES)
    request = schema.of(RunRequest)
    contract_properties = obj(obj(contract["request_schema"])["properties"])
    request_properties = obj(request["properties"])
    for field in ("thread", "delta_file"):
        assert contract_properties[field] == request_properties[field]
    attempts = obj(obj(contract["answer_schema"])["properties"])["attempts"]
    assert "new_thread" in str(attempts)
