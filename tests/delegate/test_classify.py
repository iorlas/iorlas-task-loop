"""The outcome ladder (the shelf any_agent.classify) and contract.json, replayed on fixtures taken from real runs (contract/)."""

import argparse
import io
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import pytest
from any_agent.classify import Outcome, classify
from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks
from delegate.adapters import agent_runs, codex_account
from delegate.app import answer, env, launch
from delegate.app import decide as dec
from delegate.cli import verbs
from delegate.contracts import stops
from delegate.contracts.json_types import Json, as_opt_str, obj
from delegate.domain.lanes import profiles
from delegate.domain.policy.worker import denial, denial_item
from support.case import Case
from support.procsim import real_proc

from delegate_fakes.fake_run import replay as replay_run
from test_route import ROOT, T, route

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


class Fixtures:
    def test_every_fixture_row_replays_to_its_reason(self):
        n = 0
        for name, f, row, want in all_rows():
            if "evidence" not in row:
                continue
            o = replay(row, f)
            assert (o.reason if o else None) == want, f"{name} {row['id']}"
            n += 1
        assert n > 400  # 53 + 215 + 53 + 114 + the rest

    def test_the_53_bad_requests_the_grok_batch_and_the_night_are_all_there(self):
        def count(name):
            return len(load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / name)["rows"])

        assert count("bad_request_22oct.json") == 53
        assert count("grok_spending_limit_24oct.json") == 114
        night = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "night_22oct.json")["rows"]
        assert sum(1 for r in night if r["expected_reason"] == "bad_request") == 53
        assert sum(1 for r in night if r["expected_reason"] is None) == (len(night) - 53)

    def test_every_declared_reason_has_a_fixture_row_and_every_fixture_reason_is_declared(self):
        used = {want for _, _, _, want in all_rows() if want}
        declared = set(CONTRACT["reasons"])
        assert (declared - used) == set(), "a reason without a fixture row"
        assert (used - declared) == set(), "a fixture reason contract.json does not declare"

    def test_a_row_that_is_not_from_a_real_run_says_so(self):
        for name, _f, row, _want in all_rows():
            if row.get("synthetic"):
                assert row.get("source"), name

    def test_bad_request_never_benches_a_pair(self):
        assert not stops.benches_pair("bad_request")
        assert CONTRACT["reasons"]["bad_request"]["health"] == "none"
        for _name, f, row, want in all_rows():
            if want == "bad_request":
                got = replay(row, f)
                assert got is not None
                assert not stops.benches_pair(got.reason), row["id"]
        for reason in ("network", "killed", "timeout", "secrets", "schema_invalid", "held", "busy", "caller"):
            assert not stops.benches_pair(reason), reason
        assert stops.benches_pair("rate_limited") and stops.benches_pair("credit_exhausted")


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


class Stop(Case):
    """settle() + result() turn a classified row into the contract 4 answer; a request or machine fault leaves the lane state as it was."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(env, "config_dir", return_value=Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def answer(self, o, lane):
        res = launch.settler().apply({}, o, {"lane": lane}, T, "cli", SimpleNamespace(timeout=30), 1, "tail", reset=lambda: T + 3600)
        return answer.result(as_opt_str(res.pop("outcome")), **res)

    def test_every_fixture_row_answers_with_its_expected_stop_tuple_and_fits_the_schema(self):
        n = 0
        for path in FIXTURES:
            f = load(path)
            for row in f["rows"]:
                want_reason = row.get("expected_reason", f.get("expected_reason"))
                if "evidence" not in row or not want_reason:
                    continue
                before = env.load_state().out or None
                lane = f.get("lane", "OPENAI_SUBSCRIPTION")
                o = replay(row, f)
                assert o is not None
                r = self.answer(o, lane)
                if (
                    launch.settler().net_pass(o, {"lane": lane}).reason == "network" and o.reason != "network"
                ):  # a failure that words a dropped connection is the network's (R17)
                    assert r["stop"]["reason"] == "network", f"{path.name} {row['id']}"
                    continue
                assert stop_tuple(r) == expected_tuple(f, row, want_reason), f"{path.name} {row['id']}"
                assert answer.schema_problem(r, CONTRACT["answer_schema"]) is None, f"{path.name} {row['id']}"
                if r["stop"]["scope"] in ("bead", "caller", "machine"):
                    assert (env.load_state().out or None) == before, (
                        f"{path.name} {row['id']}: a {r['stop']['scope']}-scoped fault touched the lane's state"
                    )
                env.update_state(lambda s: s.out.clear())
                n += 1
        assert n > 250

    def test_golden_the_53_bad_requests_map_to_caller_needs_owner_none(self):
        f = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "bad_request_22oct.json")
        assert len(f["rows"]) == 53
        for row in f["rows"]:
            assert stop_tuple(self.answer(replay(row, f), "OPENAI_SUBSCRIPTION")) == ("bad_request", "caller", "needs_owner", "none"), row[
                "id"
            ]
        assert (env.load_state().out or None) is None  # not one of them marks the lane

    def test_golden_the_grok_batch_is_a_lane_out_with_no_time_and_marks_the_lane_once_for_all(self):
        f = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "grok_spending_limit_24oct.json")
        assert len(f["rows"]) == 114
        for row in f["rows"]:
            r = self.answer(replay(row, f), "GROK_SUBSCRIPTION")
            assert stop_tuple(r) == ("credit_exhausted", "lane", "needs_owner", "none"), row["id"]
            assert r["stop"]["retry"]["at"] is None
        assert "GROK_SUBSCRIPTION" in env.load_state().out

    def test_golden_the_22_oct_night_has_53_bad_requests_and_every_other_row_is_done(self):
        f = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "night_22oct.json")
        assert len(f["rows"]) == 268
        tuples = [stop_tuple(self.answer(o, "OPENAI_SUBSCRIPTION")) if (o := replay(row, f)) else None for row in f["rows"]]
        assert tuples.count(("bad_request", "caller", "needs_owner", "none")) == 53
        assert tuples.count(None) == (268 - 53)
        assert (env.load_state().out or None) is None

    def test_credit_exhausted_marks_the_lane_with_no_retry_time(self):
        row = load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "grok_spending_limit_24oct.json")["rows"][0]
        o = replay(row, None)
        r = self.answer(o, "GROK_SUBSCRIPTION")
        out = env.load_state().out["GROK_SUBSCRIPTION"]
        assert out.until > T  # hidden from the picker (gather needs a time) and probed again later
        assert (out.reason, r["stop"]["scope"], r["stop"]["retry"]) == ("credit", "lane", {"kind": "none", "at": None})

    def test_answers_that_wait_for_a_time_say_when(self):
        r = self.answer(Outcome("rate_limited", "Usage limit reached for 5 hour", "event"), "ZAI_CODING_SUBSCRIPTION")
        assert (r["stop"]["permanence"], r["stop"]["retry"]) == ("transient", {"kind": "predicted", "at": T + 3600})
        r = self.answer(Outcome("logged_out", "Not logged in", "stderr"), "OPENAI_SUBSCRIPTION")
        assert (r["stop"]["permanence"], r["stop"]["retry"]["kind"]) == ("needs_owner", "none")
        assert "codex login" in r["stop"]["fix"]

    def test_killed_and_network_carry_resumable_and_partial_and_never_a_lane_mark(self):
        for reason in ("killed", "network"):
            res: dict[str, Json] = {"ref": "thread-1", "started": True, "partial": True}
            launch.settler().apply(
                res,
                Outcome(reason, "signal 15" if reason == "killed" else "ENOTFOUND", "exit"),
                {"lane": "OPENAI_SUBSCRIPTION"},
                T,
                "cli",
                SimpleNamespace(timeout=30),
                1,
                "",
            )
            r = answer.result(as_opt_str(res.pop("outcome")), **res)
            stop = obj(r["stop"])
            assert (stop["reason"], stop["resumable"], stop["partial"], stop["ref"]) == (reason, True, True, "thread-1")
        assert (env.load_state().out or None) is None

    def test_an_unknown_reason_still_gets_a_row_of_closed_facts(self):
        s = stops.stop_facts("some_new_reason")
        assert (s["scope"], s["permanence"], obj(s["retry"])["kind"]) == ("machine", "needs_owner", "none")
        assert answer.schema_problem(dict(answer.result("no_lane"), stop=dict(s, ref=None)), CONTRACT["answer_schema"]) is None

    def test_the_schema_refuses_an_answer_with_a_missing_or_wrong_field(self):
        good = answer.result("no_lane")
        assert answer.schema_problem(good, CONTRACT["answer_schema"]) is None
        done = answer.result()
        assert answer.schema_problem(done, CONTRACT["answer_schema"]) is None
        assert done["stop"] is None
        for bad in (
            dict(good, stop=dict(obj(good["stop"]), scope="planet")),
            {k: v for k, v in good.items() if k != "usage"},
            {k: v for k, v in good.items() if k != "stop"},
            dict(good, contract=2),
            dict(good, denied=[{"kind": "whim", "tool": "Bash"}]),
        ):
            assert answer.schema_problem(bad, CONTRACT["answer_schema"]) is not None

    def test_a_bad_flag_or_argument_of_run_is_a_bad_request_answer_and_other_commands_keep_exit_2(self):
        cases = [
            ["run", "worker", "--nope", "--unattended"],
            ["run", "--unattended"],
            ["run", "worker", "--timeout", "soon", "--unattended"],
        ]
        for argv in cases:
            with patch("sys.stdout", io.StringIO()) as out, pytest.raises(SystemExit) as ex:
                route.main(argv)
            assert ex.value.code == 0, argv
            r = json.loads(out.getvalue())
            assert stop_tuple(r) == ("bad_request", "caller", "needs_owner", "none"), argv
            assert r["stop"]["fix"].startswith("update task-loop or delegate: "), argv
            assert answer.schema_problem(r, CONTRACT["answer_schema"]) is None, argv
        with patch("sys.stderr", io.StringIO()), pytest.raises(SystemExit) as ex:
            route.main(["status", "--nope"])
        assert ex.value.code == 2

    def test_sandbox_limit_is_listed_and_never_counted(self):
        d = denial_item(denial("sandbox_limit", "bash", {"command": "ps aux"}))
        assert (d["kind"], d["path"]) == ("sandbox_limit", None)
        assert denial_item(denial("secret", "bash", {"command": "cat ~/.ssh/id_rsa"}))["path"] == ".ssh"
        assert denial_item(denial("policy", "edit", {"filePath": "x.py"}))["path"] == "x.py"
        assert sum(1 for x in [d, denial_item(denial("policy", "bash", {}))] if x.get("kind") != "sandbox_limit") == 1

    def test_contract_4_has_no_wire_left(self):
        gone = ("v", "status", "reason", "next", "retry_after")
        for r in (answer.result(), answer.result("no_lane"), answer.result("rate_limited", retry_after=T)):
            assert r["contract"] == 4
            for k in gone:
                assert k not in r
        for k in ("wire_reasons", "wire_default"):
            assert k not in CONTRACT
        for name, row in CONTRACT["reasons"].items():
            assert "wire" not in row, name
        assert (set(CONTRACT["answer_schema"]["properties"]) & set(gone)) == set()
        assert CONTRACT["denied_kinds"] == ["policy", "sandbox_limit", "secret"]

    def test_the_old_wire_is_gone_from_the_source(self):
        for path in [
            *(ROOT / "src" / "delegate").rglob("*.py"),
            ROOT / "src" / "delegate" / "data" / "contract.json",
        ]:
            text = path.read_text(encoding="utf-8")
            for word in ("to_wire_v2", "vendor_prework", "lane_out", "wire_reasons", "wire_default"):
                assert word not in text, f"{path.name}: {word}"

    def test_the_declared_facts_are_closed_lists(self):
        for _reason, row in CONTRACT["reasons"].items():
            assert row["scope"] in CONTRACT["scopes"]
            assert row["permanence"] in CONTRACT["permanences"]
            assert row["retry"] in CONTRACT["retry_kinds"]
            assert row["health"] in CONTRACT["health_effects"]
        assert CONTRACT["contract"] == 4


class Docs:
    """The words the orchestrator reads match the code (delegate-fvk): flags, reasons, no dead compat."""

    SRC = (ROOT / "src" / "delegate" / "cli" / "parser.py").read_text(encoding="utf-8")
    # flags of other tools, named in prose
    FOREIGN: ClassVar[dict[str, set[str]]] = {"codex.md": {"--write", "--background", "--skip-git-repo-check"}}

    def test_run_args_are_the_flags_of_run(self):
        assert set(re.findall(r'ru\.add_argument\(\s*"(--[a-z-]+)"', self.SRC)) == set(CONTRACT["run_args"])


class Launchers(Case):
    """The three harnesses end in the same ladder; the supervisor replays the events of a fixture row (delegate_fakes/fake_run.py)."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        for p in (
            patch.object(env, "config_dir", return_value=Path(self.tmp.name)),
            patch.object(agent_runs, "run"),
            patch.object(agent_runs, "lanes"),
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
            res = launch.launch_worker(d, "brief", self.a, "rid12345", T, env.load_routing(), {}, RunHooks())
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

    def test_a_bad_request_row_through_the_codex_launcher_leaves_the_lane_alone(self):
        for row in load(ROOT / "tests" / "delegate" / "contract" / "fixtures" / "bad_request_22oct.json")["rows"][:3]:
            res = self.run_cli("codex", [{"type": "turn.failed", "error": {"message": row["evidence"]["vendor_err"]}}], 1)
            assert res["outcome"] == "bad_request"
        assert (env.load_state().out or None) is None

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_sigterm_with_no_error_is_killed_and_retried_not_failed(self):
        res = self.opencode([{"type": "step_finish", "part": {"tokens": {"input": 5}}}], rc=-15)
        assert res["outcome"] == "killed"
        assert "retry_after" not in res
        assert (env.load_state().out or None) is None

    def test_codex_stream_retries_do_not_fail_a_run_that_finished(self):
        res = self.run_cli(
            "codex",
            [
                {"type": "error", "message": "Reconnecting... 2/5 (idle timeout waiting for websocket)"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "all done"}},
                {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 1}},
            ],
            0,
        )
        assert (res.get("outcome"), res["text"], res["turns"]) == (None, "all done", 1)
        res = self.run_cli(
            "codex",
            [
                {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "status": "completed"}},
                {"type": "error", "message": "Reconnecting... 5/5 (websocket closed by server)"},
            ],
            1,
        )
        assert res["outcome"] == "worker_failed"
        assert "Reconnecting... 5/5" in res["say"]

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

    def test_a_runner_kind_that_is_not_a_launcher_is_a_setup_error(self):
        kinds = {obj(c)["runner"] for c in obj(env.load_routing()["lanes"]).values()}
        assert set(profiles.REGISTRY) == {"codex", "opencode", "claude_p"}
        assert kinds <= {"codex", "opencode", "claude_p", "agent_tool"}
        d = {
            "action": "run",
            "role": "worker",
            "lane": "OPENAI_SUBSCRIPTION",
            "model": "m",
            "effort": "high",
            "mode": "write",
            "how": {"kind": "codexx", "cwd": self.tmp.name},
        }
        a = argparse.Namespace(
            role="worker",
            authored_by=None,
            premium=None,
            allow_degraded=False,
            claude_usage=None,
            cwd=None,
            resume=None,
            cap=None,
            brief=None,
            timeout=5,
            unattended=True,
            schema=None,
            parent=None,
            task=None,
            title=None,
            call_id="c#1",
        )
        with patch.object(dec, "decision", return_value=(d, {}, [], T)), patch("sys.stdout", io.StringIO()) as out:
            verbs.cmd_run(a, env.load_routing())
        r = json.loads(out.getvalue())
        assert (r["stop"]["reason"], r["call_id"]) == ("setup", "c#1")
        assert "codexx" in r["say"]
