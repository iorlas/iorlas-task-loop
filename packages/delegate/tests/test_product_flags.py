"""Product requests derive harness policy from delegate's settings and threads."""

from pathlib import Path

import pytest

from delegate import api
from delegate.app import answer, env, threads
from delegate.contracts import codec, schema
from delegate.contracts.json_types import obj
from delegate.contracts.state import OutState, StateDoc, ThreadRecord
from delegate.contracts.wire import RunRequest, RunResult
from tltestkit.tmpdir import TemporaryDirectory


@pytest.mark.parametrize(
    "role,prefer,pin", [("worker", "", ["openai"]), ("worker", "codex-ish", ["codex-ish"]), ("reviewer", "xai", []), ("planner", "xai", [])]
)
def test_api_derives_worker_policy(monkeypatch, role, prefer, pin):
    cfg = env.load_routing()
    obj(cfg["settings"]).update(writer_family=["openai"], writer_exec_allow=[["python"]], writer_read_roots=["/read"])
    monkeypatch.setattr(env, "load_routing", lambda: cfg)
    calls = []

    class Run:
        def __init__(self, args, cfg, **kw):
            calls.append(args)

        def call(self):
            return answer.result(None)

    monkeypatch.setattr(api.run_app, "Run", Run)
    res = api.run(RunRequest(role=role, brief_file="whole", cwd="tree", prefer=prefer, writer_exec=(not prefer)))
    assert res.stop is None
    assert calls[0].only_family == pin
    assert calls[0].read_root == (["/read"] if role == "worker" else [])
    assert calls[0].writer_exec_allow == ([["python"]] if role == "worker" and not prefer else [])


@pytest.mark.parametrize("pin,grant", [([], [["python"]]), (["claude"], [["python"]]), (["openai"], [])])
def test_writer_exec_refuses_without_codex_pin_and_grant(monkeypatch, pin, grant):
    cfg = env.load_routing()
    obj(cfg["settings"]).update(writer_family=pin, writer_exec_allow=grant)
    monkeypatch.setattr(env, "load_routing", lambda: cfg)
    monkeypatch.setattr(api.run_app, "Run", lambda *a, **kw: pytest.fail("must not launch"))
    res = api.run(RunRequest(role="worker", brief_file="whole", cwd="tree", writer_exec=True))
    assert res.stop is not None
    assert (res.stop.scope, res.stop.permanence) == ("caller", "needs_owner")
    assert res.say == "writer_exec needs the writer pinned to the Codex family and a writer_exec_allow grant in delegate's routing settings"


@pytest.mark.parametrize("author,record,expected", [(None, True, "openai"), ("claude", True, "claude"), (None, False, None)])
def test_reviewer_author_comes_from_writer_thread(monkeypatch, author, record, expected):
    cfg = env.load_routing()
    account = next(n for n, spec in obj(cfg["accounts"]).items() if obj(spec)["family"] == "openai")
    state = StateDoc(threads={"task/writer": ThreadRecord(ref="r", account=account, model="m")} if record else {})
    monkeypatch.setattr(env, "load_state", lambda: state)
    calls = []

    class Run:
        def __init__(self, args, cfg, **kw):
            calls.append(args)

        def call(self):
            return answer.result(None)

    monkeypatch.setattr(api.run_app, "Run", Run)
    api.run(RunRequest(role="reviewer", brief_file="whole", cwd="tree", task="task", authored_by=author, reviewer_other_family=True))
    assert calls[0].authored_by == expected


@pytest.mark.parametrize("until,fresh", [(None, True), (0, True), (float("inf"), False)])
def test_fallback_retake_uses_active_out_mark(until, fresh):
    with TemporaryDirectory() as folder:
        whole, delta = Path(folder) / "whole", Path(folder) / "delta"
        whole.write_text("whole")
        delta.write_text("delta")
        state = StateDoc(
            threads={"task/writer": ThreadRecord(ref="r", account="fallback", model="m", fallback=True, first_account="first")},
            out={} if until is None else {"first": OutState(until=until)},
        )
        request = RunRequest(role="worker", task="task", thread="writer", brief_file=str(whole), delta_file=str(delta), cwd=folder)
        plan = threads.plan(request, state, env.typed_routing(env.load_routing()))
        assert plan.resume == (None if fresh else "r")
        assert plan.brief_text == ("whole" + threads.TAKEOVER_NOTE if fresh else "delta")
        assert plan.takeover is fresh


def test_settle_stores_fallback():
    state = StateDoc()
    res = codec.from_json(RunResult, answer.result(None, ref="r", fallback=True, first_account="first"))
    threads.settle(state, "task/writer", res)
    assert state.threads["task/writer"].fallback is True
    assert state.threads["task/writer"].first_account == "first"


def test_product_schema_and_settings():
    properties = obj(obj(api.contract()["request_schema"])["properties"])
    actual = obj(schema.of(RunRequest)["properties"])
    for name in ("prefer", "writer_exec", "reviewer_other_family"):
        assert properties[name] == actual[name]
    settings = env.settings_of(env.load_routing())
    assert (settings.writer_family, settings.writer_exec_allow, settings.writer_read_roots) == ([], [], [])


def test_prefer_overrides_settings_for_exec_admission(monkeypatch):
    cfg = env.load_routing()
    obj(cfg["settings"]).update(writer_family=["openai"], writer_exec_allow=[["python"]])
    monkeypatch.setattr(env, "load_routing", lambda: cfg)
    monkeypatch.setattr(api.run_app, "Run", lambda *a, **kw: pytest.fail("must not launch"))
    res = api.run(RunRequest(role="worker", brief_file="whole", cwd="tree", prefer="codex-ish", writer_exec=True))
    assert res.stop is not None
    assert (res.stop.scope, res.stop.permanence) == ("caller", "needs_owner")


def test_direct_delegate_wire_fields_remain_available():
    req = RunRequest(
        role="worker",
        brief_file="whole",
        cwd="tree",
        only_family=["openai"],
        authored_by="claude",
        writer_exec_allow=[["python"]],
        read_roots=["/read"],
    )
    argv = req.to_argv("route.py", contract=api.contract())
    for flag, value in (("--only-family", "openai"), ("--authored-by", "claude"), ("--read-root", "/read")):
        assert argv[argv.index(flag) + 1] == value
    assert "--writer-exec-allow" in argv


def test_writer_settings_accept_owner_overrides():
    env.update_config(lambda config: config.update(writer_family=["openai"], writer_exec_allow=[["python"]], writer_read_roots=["/read"]))
    settings = env.settings_of(env.load_routing())
    assert (settings.writer_family, settings.writer_exec_allow, settings.writer_read_roots) == (["openai"], [["python"]], ["/read"])
