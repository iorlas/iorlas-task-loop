"""The engine supplies thread identities and leaves thread recovery to delegate."""

from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from taskloop.adapters import delegate as adapter
from taskloop.app.workers import call_state, worker_call, worker_recovery, worker_request
from taskloop.app.workers.call import Call
from taskloop.domain.lanes import policy as lp
from taskloop.domain.lanes.retry import PLAN
from tlkernel import wire
from tlkernel.delegate import DelegateResult, Retry, RunRequest, StopFacts
from tlkernel.delegateport import Answer, Completed
from tltestkit.tmpdir import TemporaryDirectory


def noop(*args, **kwargs):
    return None


def host():
    e = SimpleNamespace(
        cfg=SimpleNamespace(base="main", writer_exec=False, reviewer_other_family=True, stage_checks=[]),
        bead="t-1",
        wt="/repo",
        session="run",
        plan_data=None,
        budget=SimpleNamespace(labels=[]),
        checker=SimpleNamespace(split=lambda: SimpleNamespace(engine_recipes=lambda _: [])),
    )
    return e


def test_request_has_thread_and_never_resume(monkeypatch):
    monkeypatch.setattr(worker_request.writer_pin, "prefer", lambda *a: "")
    c = Call("write", "worker", {}, "/repo", "", "", None, ("write", 1), "writer", None, "write")
    req = worker_request.request(host(), c, "", 60, 30)
    assert req.thread == "writer"
    assert req.delta_path == ""
    assert "resume" not in req.to_dict()
    with pytest.raises(wire.StaleRecord):
        wire.load(RunRequest, dict(req.to_dict(), v=0))


@pytest.mark.parametrize("scope", ["lane", "model"])
@pytest.mark.parametrize("attempt", [0, 1, 5])
def test_lane_stops_do_not_restart_threads(scope, attempt):
    ctx = lp.Ctx(attempt=attempt)
    predicted = lp.Stop(scope, "transient", "predicted", retry_at=123, lane="lane", model="model")
    assert lp.decide(predicted, ctx) == lp.Yield("PAUSE_LANE", 123)
    poll = lp.Stop(scope, "transient", "poll", lane="lane", model="model")
    assert lp.decide(poll, ctx) == lp.Reroute(scope)


@pytest.mark.parametrize("retry", ["none", "predicted"])
@pytest.mark.parametrize("hurt", [False, True])
def test_bead_failure_is_final(retry, hurt):
    stop = lp.Stop("bead", "transient", retry, timed_out=hurt)
    assert lp.decide(stop, lp.Ctx(node="write")) == lp.Fail("ASK_STUCK" if hurt else "FAULT_INFRA", "worker_failed")
    assert lp.decide(lp.Stop("caller", "needs_owner"), lp.Ctx()) == lp.Fail("FAULT_BAD_REQUEST")


def test_resume_recovery_policy_is_removed():
    assert "resume_refused" not in PLAN.rows
    assert not {"resumed", "resume_refused"} & {f.name for f in fields(lp.Ctx)}
    for facts in lp.LEGAL:
        action = lp.decide(lp.Stop(*facts), lp.Ctx(secret_fp=True))
        if isinstance(action, lp.NewThread):
            assert action.note == "apply_patch"


def test_interrupted_call_keeps_thread_and_continuation(monkeypatch):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        e = host()
        e.run_dir, e.call_dir, e.log = root, lambda: root / "calls", SimpleNamespace(note=noop)
        monkeypatch.setattr(worker_request.writer_pin, "prefer", lambda *a: "")
        w = worker_call.WorkerCall(e, worker_call.Ops(
            summarize=noop, read_only_command=noop, blocked=noop, stop_why=noop, stop_say=noop, after=noop,
        ))
        prepared = SimpleNamespace(execution_id="same", snapshot=None)
        monkeypatch.setattr(w, "prepare", lambda c: prepared)
        st = call_state.CallState("run", "t-1", ("write", 1), ref="vendor-ref", execution_id="same")
        monkeypatch.setattr(worker_recovery.done_memo, "recall", lambda *a: None)
        monkeypatch.setattr(worker_recovery.call_state, "load_for", lambda *a: st)
        c = Call("write", "worker", {}, "/repo", "", "", None, st.key, "writer", None, "write")
        w.attach(c)
        assert c.thread == "writer"
        assert c.delta == worker_recovery.RESUME_AFTER_STOP
        assert "Continue from where you stopped" in c.delta
        assert not hasattr(c, "resume")
        req = worker_request.request(e, c, "", 60, 30)
        assert req.thread == "writer"
        assert "resume" not in req.to_dict()


def test_writer_loop_sends_delta_and_pauses(monkeypatch):
    e = host()
    e.writer = SimpleNamespace(delegate="vendor-ref")
    e.stats = {"nodes": 0}
    e.halt_point = noop
    e.waits = SimpleNamespace(budget_check=noop)
    e.publish_plan = noop
    e.steps = SimpleNamespace(begin=noop, move=noop)
    e.log = SimpleNamespace(emit=noop)
    w = worker_call.WorkerCall(e, worker_call.Ops(
        summarize=noop, read_only_command=noop, blocked=noop, stop_why=noop, stop_say=noop, after=noop,
    ))
    monkeypatch.setattr(w, "attach", lambda c: None)
    sent = []

    def fake_call(c):
        sent.append((c.thread, c.text, c.delta))
        stop = StopFacts(reason="rate_limited", scope="lane", permanence="transient", retry=Retry(kind="predicted", at=123))
        return Answer(DelegateResult(stop=stop), {})

    monkeypatch.setattr(w, "call_once", fake_call)

    class Paused(Exception):
        pass

    def end(c, res, stop, action):
        assert action == lp.Yield("PAUSE_LANE", 123)
        raise Paused

    monkeypatch.setattr(w.acts, "end", end)
    with pytest.raises(Paused):
        w.run("write", "write", "full prompt", resume_key="writer", delta="continuation")
    assert sent == [("writer", "full prompt", "continuation")]


def test_adapter_writes_delta_beside_full_brief():
    req = RunRequest(role="worker", brief_path="", cwd="/repo", schema_path="", thread="writer")

    def runner(argv, **kw):
        request = kw["request"]
        assert request.thread == "writer"
        assert request.resume is None
        assert Path(request.brief_file).read_text() == "full"
        assert Path(request.delta_file).read_text() == "delta"
        assert Path(request.delta_file).parent == Path(request.brief_file).parent
        return Completed(argv, 0, '{"contract":4,"stop":null,"ref":"delegate-ref"}')

    answer = adapter.call(adapter.resolve(), req, "full", {}, runner, env={}, delta="delta")
    assert answer.res.ref == "delegate-ref"
