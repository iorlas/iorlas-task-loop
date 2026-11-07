"""delegate-np7: one supervisor for Codex, Claude Code and opencode. Fixture replays: a fake CLI prints a recorded stream and never exits
(or stalls);
no real model is called. Grace and stall are cut to ~1 s through the supervisor constants."""

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import ClassVar
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent.harnesses import opencode_sandbox

from tltestkit.case import Case
from tltestkit.fake_clock import SteppingClock
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "delegate"))
import shutil

from any_agent import watch
from any_agent.harnesses import claude
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks

from delegate.adapters import codex_account, git
from delegate.app import env, harnesses, launch
from delegate.contracts.json_types import Json
from tltestkit import fake_worker
from tltestkit.fake_worker import Jump

T = 1_000_000.0
LIMIT_S = 30  # replays wait out the grace and stall limits (about 4 s each)


def j(**kw):
    return json.dumps(kw)


CLAUDE_TOOL = j(
    type="assistant",
    message={
        "id": "m1",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "content": [{"type": "tool_use", "id": "tu1", "name": "Bash"}],
    },
)
CLAUDE_TOOL_DONE = j(type="user", message={"content": [{"type": "tool_result", "tool_use_id": "tu1"}]})
CLAUDE_FINAL = j(
    type="assistant",
    message={
        "id": "m2",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "cache_read_input_tokens": 40, "output_tokens": 7},
        "content": [{"type": "text", "text": "the final words"}],
    },
)
CLAUDE_RESULT = j(
    type="result",
    result="claude answer",
    session_id="sess-1",
    is_error=False,
    num_turns=2,
    total_cost_usd=0.25,
    usage={"input_tokens": 15, "cache_read_input_tokens": 40, "output_tokens": 9},
)
OC_STEP_TOOLS = j(type="step_finish", sessionID="ses_1", part={"reason": "tool-calls", "tokens": {"input": 10, "output": 1}})
OC_TEXT = j(type="text", sessionID="ses_1", part={"text": "opencode answer"})
OC_STEP_STOP = j(
    type="step_finish", sessionID="ses_1", part={"reason": "stop", "tokens": {"input": 20, "output": 4, "cache": {"read": 5, "write": 0}}}
)
CODEX_STARTED = j(type="thread.started", thread_id="th-1")
CODEX_MSG = j(type="item.completed", item={"id": "i1", "type": "agent_message", "text": "codex answer"})
CODEX_CMD = j(type="item.completed", item={"id": "i2", "type": "command_execution", "command": "ls", "status": "completed", "exit_code": 0})
CODEX_DONE = j(type="turn.completed", usage={"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 7})


class Replay(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.pidfile = self.base / "pid"
        self.cfg = self.base / "cfg"
        self.cfg.mkdir()
        stall_patch = mock.patch.object(watch, "STALL_S", 1)
        stall_patch.start()
        self.addCleanup(stall_patch.stop)
        limits = mock.patch.dict(harnesses.LIMITS, {k: dataclasses.replace(v, grace_s=1) for k, v in harnesses.LIMITS.items()})
        limits.start()
        self.addCleanup(limits.stop)
        self.clock = SteppingClock(0.25)  # a silence or a grace passes in polls, not seconds
        clock = mock.patch.object(harnesses, "CLOCK", self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        penv = dict(os.environ, DELEGATE_CONFIG_DIR=str(self.cfg), HOME=str(self.base), CODEX_HOME=str(self.base))
        for p in (
            mock.patch.dict(os.environ, penv),
            mock.patch.object(sys, "platform", "darwin"),
            mock.patch.object(opencode_sandbox, "write_shell"),
            mock.patch.object(env, "child_env", side_effect=lambda extra=None: dict(os.environ, **(extra or {}))),
            mock.patch.object(codex_account, "thread_total", return_value=None),
            mock.patch.object(codex_account, "child_tokens", return_value=({"in": 0, "cached": 0, "out": 0}, 0)),
            mock.patch.object(codex_account, "context_k", return_value=None),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.a = argparse.Namespace(resume=None, schema=None, timeout=0, role="worker")

    def d(self, kind) -> dict[str, Json]:
        lane = {"codex": "OPENAI_SUBSCRIPTION", "claude": "CLAUDE_SUBSCRIPTION", "opencode": "GROK_SUBSCRIPTION"}[kind]
        how = {
            "kind": {"codex": "codex", "claude": "claude_p", "opencode": "opencode"}[kind],
            "model": "m",
            "cwd": str(self.base),
            "write": False,
            "read_only": False,
            "cap": 1,
            "sandbox": "read-only",
            "cli": ["codex", "exec"],
            "isolation": [],
        }
        return {"lane": lane, "model": "m", "effort": "high", "role": "worker", "how": how}

    def launch(self, kind, *script, a=None):
        """The worker plays `script` (packages/testkit/src/tltestkit/fake_worker.py); -> the answer and the workers started."""
        a = a or self.a
        d = self.d(kind)
        exe = "/fake/" + kind
        with (
            fake_worker.install(list(script), clock=self.clock) as started,
            mock.patch.object(shutil, "which", return_value=exe),
            mock.patch.object(OpenCodeHarness, "find_exe", return_value=exe),
            mock.patch.object(git, "_git", return_value=None),  # no git here: the tree is not a repository
        ):
            r = launch.launch_worker(d, "brief", a, "rid12345", T, env.load_routing(), RunHooks())
        return r, started

    CASES: ClassVar = {
        "codex": ([CODEX_STARTED, CODEX_CMD, CODEX_MSG, CODEX_DONE], "codex answer"),
        "claude": ([CLAUDE_TOOL, CLAUDE_TOOL_DONE, CLAUDE_FINAL, CLAUDE_RESULT], "claude answer"),
        "opencode": ([OC_STEP_TOOLS, OC_TEXT, OC_STEP_STOP], "opencode answer"),
    }

    def test_a_stream_ending_in_its_completion_event_with_a_process_that_never_exits_is_done(self):
        for kind, (lines, text) in self.CASES.items():
            with self.subTest(kind):
                r, started = self.launch(kind, *lines)
                assert (r.get("outcome"), r["text"]) == (None, text), r
                assert r["stream_tail"] and lines[-1] in r["stream_tail"][-1], r["stream_tail"]  # the tail is kept on any kill
                assert [p.stopped for p in started] == [True]  # the tree was stopped, not left running
                if kind != "claude":
                    assert r["warnings"] == ["answer_done_process_alive"]

    def test_a_final_message_without_the_completion_event_ends_the_run_too(self):
        r, _ = self.launch("claude", CLAUDE_TOOL, CLAUDE_TOOL_DONE, CLAUDE_FINAL)
        assert (r.get("outcome"), r["text"], r["warnings"]) == (None, "the final words", ["answer_done_process_alive"])
        assert r["tokens"] == {"in": 55, "cached": 40, "out": 9}  # no result event: usage folded from the stream's requests
        assert (r["acct"]["in_fresh"], r["acct"]["cache_read"], r["acct"]["out"]) == (15, 40, 9)
        r, started = self.launch("codex", CODEX_STARTED, CODEX_MSG)
        assert (r.get("outcome"), r["text"]) == (None, "codex answer")
        assert started[0].stopped

    def test_a_later_event_resets_the_grace(self):
        r, started = self.launch("claude", CLAUDE_RESULT, Jump(0.7), CLAUDE_RESULT)
        assert (r.get("outcome"), r["text"]) == (None, "claude answer")
        assert started[0].stopped
        assert self.clock.t - T >= 0.7 + 1.0  # the second turn's event, 0.7 s on, restarted the 1 s grace

    def test_a_stalled_stream_is_killed_and_its_tail_logged(self):
        stalls = {"codex": [CODEX_STARTED, CODEX_CMD], "claude": [CLAUDE_TOOL, CLAUDE_TOOL_DONE], "opencode": [OC_STEP_TOOLS]}
        for kind, lines in stalls.items():
            with self.subTest(kind):
                r, started = self.launch(kind, *lines)
                assert r["outcome"] == "hung", r
                assert r["stream_tail"][-1] == lines[-1]
                assert started[0].stopped

    def test_a_tool_in_flight_keeps_the_long_silence_limit(self):
        now = [0.0]
        wd = watch.Watchdog(120, 3600, clock=lambda: now[0])
        turn = watch.Turn(5, clock=lambda: now[0])
        wd.touch()
        turn.more()
        turn.tool("tu1", True)
        now[0] = watch.STALL_S + 1
        wd.poll()
        assert turn.verdict(wd) is None  # a tool owes the silence: no stall
        turn.tool("tu1", False)
        assert turn.verdict(wd) == "stall"  # the tool is back and the model is silent

    def test_turn_rules_with_an_injected_clock(self):
        now = [0.0]
        wd = watch.Watchdog(120, 600, clock=lambda: now[0])
        turn = watch.Turn(1, clock=lambda: now[0])
        wd.touch()
        turn.finished()
        now[0] = 0.5
        wd.poll()
        assert turn.verdict(wd) is None
        turn.more()
        turn.finished()
        now[0] = 1.6
        assert turn.verdict(wd) == "answer"

    def test_claude_stream_usage_sums_requests(self):
        assert claude.stream_usage([{"input_tokens": 1, "output_tokens": 2}, {"input_tokens": 3, "cache_read_input_tokens": 9}]) == {
            "input_tokens": 4,
            "cache_read_input_tokens": 9,
            "cache_creation_input_tokens": 0,
            "output_tokens": 2,
        }
        assert claude.stream_usage([]) == {}
