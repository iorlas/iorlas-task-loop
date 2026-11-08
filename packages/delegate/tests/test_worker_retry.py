"""Worker recovery stays inside delegate and uses fake launches and time."""

import argparse

import pytest
from any_agent.supervisor import RunHooks

from delegate.app import run
from delegate.app.run_legs import CONTINUE_NOTE, retry
from delegate.contracts.json_types import Json, as_str
from tltestkit.fake_clock import FakeClock


@pytest.mark.parametrize("resumable,ref", [(True, "session"), (False, "session"), (True, None)])
@pytest.mark.parametrize("reason", ["worker_failed", "timeout"])
def test_retry_once_and_merge_usage(resumable, ref, reason):
    calls = []
    first = {"outcome": reason, "resumable": resumable, "ref": ref, "cost": 2, "tokens": {"in": 10}}
    second = {"outcome": reason, "cost": 3, "tokens": {"in": 20}}

    def launch(brief, args, kind):
        calls.append((brief, args.resume, kind))
        return second

    result = retry(first, launch, "original", argparse.Namespace(resume="old", role="reviewer"))
    expected = ref if resumable else None
    assert calls == [(CONTINUE_NOTE if expected else "original", expected, "worker_retry")]
    assert result["outcome"] == reason
    assert result["cost"] == 5
    assert result["tokens"] == {"in": 30, "cached": 0, "out": 0}


@pytest.mark.parametrize("reason,exit_code", [("schema_invalid", None), ("timeout", None), ("worker_failed", -15)])
def test_schema_and_hurt_writes_are_not_retried(reason, exit_code):
    first = {"outcome": reason, "exit_code": exit_code}

    def launch(*args):
        pytest.fail("must not retry")

    assert retry(first, launch, "original", argparse.Namespace(resume=None, role="worker")) is first


@pytest.mark.parametrize("canary", [False, True])
def test_launch_retries_only_the_real_leg_once(monkeypatch, canary):
    clock = FakeClock()
    calls = []

    def launch(*args):
        calls.append(args)
        return {"outcome": "worker_failed", "resumable": True, "ref": "session"}

    monkeypatch.setattr(run.launch, "launch_worker", launch)
    worker = run.Run(argparse.Namespace(resume=None, schema=None, role="reviewer"), {},
                     now=clock.now, sleep=clock.advance, wall=clock.now)
    result = worker._launch({"lane": "lane", "model": "model"}, "original", "run", 0, RunHooks(), canary)
    assert result["outcome"] == "worker_failed"
    assert len(calls) == (1 if canary else 2)
    assert [leg["kind"] for leg in worker.attempts] == (["canary"] if canary else ["first", "worker_retry"])


@pytest.mark.parametrize("resumed", [False, True])
@pytest.mark.parametrize("reason,exit_code", [("timeout", None), ("worker_failed", -15)])
def test_hurt_write_reroutes_excluding_failed_pair(monkeypatch, resumed, reason, exit_code):
    args = argparse.Namespace(resume="session" if resumed else None, role="worker", brief=None, writer_exec_allow=[])
    worker = run.Run(args, {"lanes": {"lane": {"family": "openai"}}}, unattended=True, brief="original")
    decision: dict[str, Json] = {"action": "run", "lane": "lane", "model": "model"}
    exclusions = []

    def decide(*args, **kw):
        if len(args) > 3:
            exclusions.append(args[3])
            return {"action": "stop", "say": "none ready"}, {}, [], 0
        return decision, {}, [], 0

    monkeypatch.setattr(run.decide, "decision", decide)
    monkeypatch.setattr(run, "how_of", lambda d: argparse.Namespace(kind="codex", cwd="work"))
    monkeypatch.setattr(run.codex_policy, "require_writer_mode", lambda *a: None)
    decision["how"] = {}
    monkeypatch.setattr(run.git, "state", lambda cwd: {})
    monkeypatch.setattr(worker, "_run", lambda *a: {
        "outcome": reason, "exit_code": exit_code, "lane": "lane", "model": "model", "say": "failed",
    })
    worker._go()
    assert exclusions == ([] if resumed else [frozenset({("lane", "model")})])
    assert ("no reroute: none ready" in as_str(worker.out["say"])) is not resumed


@pytest.mark.parametrize("first", [
    {"outcome": None},
    {"outcome": "network"},
    {"outcome": "logged_out"},
    {"outcome": "schema_invalid", "retry_after": 100},
])
def test_other_stop_facts_are_untouched(first):
    def launch(*args):
        pytest.fail("must not retry")

    assert retry(first, launch, "original", argparse.Namespace(resume=None, role="reviewer")) is first


def test_predicted_worker_failure_retries_in_place():
    calls = []

    def launch(brief, args, kind):
        calls.append((brief, args.resume, kind))
        return {"outcome": None}

    result = retry({"outcome": "worker_failed", "retry_after": 100}, launch,
                   "original", argparse.Namespace(resume=None, role="worker"))
    assert result["outcome"] is None
    assert calls == [("original", None, "worker_retry")]
