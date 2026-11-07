"""The outcome ladder (the shelf any_agent.classify) and contract.json, replayed on fixtures taken from real runs (contract/)."""

import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from any_agent.classify import classify
from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks
from delegate_fakes.fake_run import replay as replay_run
from test_route import ROOT, T

from delegate.adapters import codex_account
from delegate.app import env, launch
from delegate.contracts.json_types import Json
from tltestkit.case import Case
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory

FIXTURES = sorted((ROOT / "tests" / "delegate" / "contract" / "fixtures").glob("*.json"))
CONTRACT = json.loads((ROOT / "src" / "delegate" / "data" / "contract.json").read_text(encoding="utf-8"))
LAUNCH_ONLY = {
    "duplicate_task",
    "busy",
    "no_lane",
    "caller",
    "engine_only_unenforced",
    "crash",
    "schema_invalid",
    "lock",
    "setup",
    "held",
}  # answered outside the ladder


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay(row, f):
    ev = row["evidence"]
    return classify(ev["rc"], ev["vendor_err"], ev["stderr"], ev["timed_out"], ev["work_seen"], ev["structured"])


def reason_of(
    rc: int | None,
    vendor_err: str | None = "",
    stderr: str | None = "",
    timed_out: bool = False,
    work_seen: bool = False,
    structured: Mapping[str, Json] | None = None,
) -> str | None:
    """The reason the ladder gives for a run, None when the run is done."""
    o = classify(rc, vendor_err, stderr, timed_out, work_seen, structured)
    return o.reason if o else None


def all_rows():
    for path in FIXTURES:
        f = load(path)
        for row in f["rows"]:
            yield path.name, f, row, row.get("expected_reason", f.get("expected_reason"))




def stop_tuple(r):
    s = r["stop"]
    return (s["reason"], s["scope"], s["permanence"], s["retry"]["kind"]) if s else None


def expected_tuple(f, row, reason):
    """What a fixture row must answer with: its own or its file's `expected_stop`, else the reason's row of contract.json (None: done)."""
    es = row.get("expected_stop") or f.get("expected_stop")
    if es:
        return (es["reason"], es["scope"], es["permanence"], es["retry_kind"])
    if not reason:
        return None
    c = CONTRACT["reasons"][reason]
    return (reason, c["scope"], c["permanence"], c["retry"])






class Launchers(Case):
    """The three harnesses end in the same ladder; the supervisor replays the events of a fixture row (delegate_fakes/fake_run.py)."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        for p in (
            patch.object(env, "config_dir", return_value=Path(self.tmp.name)),
            patch.object(shutil, "which", return_value="cli"),
            patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
            patch.object(sys, "platform", "darwin"),
            patch.object(opencode_sandbox, "write_shell"),
            patch.object(env, "child_env", return_value={}),
            patch.object(codex_account, "thread_total", return_value=None),
            patch.object(codex_account, "child_tokens", return_value=({"in": 0, "cached": 0, "out": 0}, 0)),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.a = SimpleNamespace(resume=None, schema=None, timeout=30, role="worker")

    def run_cli(self, kind, lines, rc, err="", lane="OPENAI_SUBSCRIPTION", **how):
        d = {
            "lane": lane,
            "model": "m",
            "effort": "high",
            "role": "worker",
            "how": dict(
                kind=kind, model="m", cwd=self.tmp.name, write=False, sandbox="read-only", cli=["codex", "exec"], isolation=[], **how
            ),
        }
        with replay_run(lines, rc, err):
            res = launch.launch_worker(d, "brief", self.a, "rid12345", T, env.load_routing(), RunHooks())
        res.pop("stderr", None)
        return res

    def opencode(self, lines, rc=1, **kw):
        return self.run_cli("opencode", lines, rc, lane=kw.pop("lane", "GROK_SUBSCRIPTION"), **kw)

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_grok_row_through_the_opencode_launcher_marks_the_lane_out_without_a_time(self):
        row = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "grok_spending_limit_24oct.json")["rows"][0]
        res = self.opencode([{"type": "error", "error": {"name": "APIError", "data": {"message": row["evidence"]["vendor_err"]}}}])
        assert (res["outcome"], res.get("retry_after")) == ("credit_exhausted", None)
        assert "GROK_SUBSCRIPTION" in env.load_state().out


    @real_proc("delegate: a worker, git or CLI process")
    def test_a_sigterm_with_no_error_is_killed_and_retried_not_failed(self):
        res = self.opencode([{"type": "step_finish", "part": {"tokens": {"input": 5}}}], rc=-15)
        assert res["outcome"] == "killed"
        assert "retry_after" not in res
        assert (env.load_state().out or None) is None


    @real_proc("delegate: a worker, git or CLI process")
    def test_a_workers_own_words_about_a_rate_limit_never_take_a_lane_out(self):
        words = "The batch is queued behind a rate limit on the Unity side; quota 429 seen in the log."
        res = self.run_cli("codex", [{"type": "item.completed", "item": {"type": "agent_message", "text": words}}], 1)
        assert res["outcome"] == "worker_failed"
        res = self.run_cli(
            "claude_p",
            [{"type": "result", "is_error": True, "result": words, "num_turns": 6, "session_id": "s1"}],
            1,
            lane="CLAUDE_SUBSCRIPTION",
            cap=1,
            read_only=False,
        )
        assert res["outcome"] == "worker_failed"
        res = self.opencode([{"type": "text", "part": {"text": words}}], rc=1)
        assert res["outcome"] == "worker_failed"
        assert (env.load_state().out or None) is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_clis_own_error_still_does(self):
        res = self.run_cli(
            "claude_p",
            [{"type": "result", "is_error": True, "result": "API Error: 429 rate limit exceeded", "num_turns": 1}],
            1,
            lane="CLAUDE_SUBSCRIPTION",
            cap=1,
            read_only=False,
        )
        assert res["outcome"] == "rate_limited"
        assert "CLAUDE_SUBSCRIPTION" in env.load_state().out

    @real_proc("delegate: a worker, git or CLI process")
    def test_additive_usage_facts_come_from_the_events(self):
        res = self.opencode(
            [
                {"type": "step_finish", "part": {"tokens": {"input": 1000, "output": 5, "cache": {"read": 3000, "write": 0}}}},
                {"type": "step_finish", "part": {"tokens": {"input": 2000, "output": 5, "cache": {"read": 4000, "write": 0}}}},
                {"type": "text", "part": {"text": "hi"}},
            ],
            rc=0,
        )
        assert (res.get("outcome"), res["turns"], res["context_k"]) == (None, 2, 6.0)
