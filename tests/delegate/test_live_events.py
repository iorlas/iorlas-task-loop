"""DELEGATE_LIVE_FILE: the live event file for a dashboard. Fixture streams per harness replayed through the real launchers
(a fake CLI prints them and never exits); assert the kinds in order and the cmd / cmd_end id pairs. Env unset: no file."""

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "delegate"))
from delegate.adapters.harness.codex import CodexHarness
from delegate.app.publish import LiveSink, end_status
from support.case import Case
from support.procsim import real_proc

import test_stream_supervisor as tss

j = tss.j
LONG = "x" * 3000

CODEX = [
    j(type="thread.started", thread_id="th-1"),
    j(type="item.started", item={"id": "c1", "type": "command_execution", "command": "ls " + LONG, "status": "in_progress"}),
    j(
        type="item.completed",
        item={"id": "c1", "type": "command_execution", "command": "ls", "aggregated_output": "a b", "exit_code": 0, "status": "completed"},
    ),
    j(type="item.started", item={"id": "f1", "type": "file_change", "changes": [{"path": "x.py", "kind": "update"}]}),
    j(
        type="item.completed",
        item={"id": "f1", "type": "file_change", "changes": [{"path": "x.py", "kind": "update"}], "status": "completed"},
    ),
    j(type="item.completed", item={"id": "r1", "type": "reasoning", "text": "plan " * 200}),
    j(type="item.completed", item={"id": "m1", "type": "agent_message", "text": "done"}),
    j(type="weird.event", payload="secret"),
    j(type="turn.completed", usage={"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 7}),
]
CLAUDE = [
    j(
        type="assistant",
        message={
            "id": "m1",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}},
                {"type": "tool_use", "id": "tu2", "name": "Edit", "input": {"file_path": "skills/x.py"}},
            ],
        },
    ),
    j(
        type="user",
        message={
            "content": [
                {"type": "tool_result", "tool_use_id": "tu1", "content": "a b"},
                {"type": "tool_result", "tool_use_id": "tu2", "content": [{"type": "text", "text": "ok"}]},
            ]
        },
    ),
    tss.CLAUDE_FINAL,
    tss.CLAUDE_RESULT,
]
OPENCODE = [
    j(type="step_start", sessionID="ses_1", part={}),
    j(
        type="tool_use",
        sessionID="ses_1",
        part={
            "callID": "o1",
            "tool": "bash",
            "state": {
                "status": "completed",
                "input": {"command": "ls"},
                "output": "a b",
                "metadata": {"exit": 0},
                "time": {"start": 1000, "end": 1500},
            },
        },
    ),
    j(
        type="tool_use",
        sessionID="ses_1",
        part={"callID": "o2", "tool": "edit", "state": {"status": "completed", "input": {"filePath": "skills/x.py"}, "output": "ok"}},
    ),
    tss.OC_STEP_TOOLS,
    tss.OC_TEXT,
    tss.OC_STEP_STOP,
]


class LiveFile(Case):
    base: Path
    setup_method = tss.Replay.setup_method
    d, alive = tss.Replay.d, tss.Replay.alive  # launch() reads self.d(kind)

    def run_kind(self, kind, lines, live_path):
        env = {"DELEGATE_LIVE_FILE": str(live_path)} if live_path else {}
        with mock.patch.dict(os.environ, env):
            if not live_path:
                os.environ.pop("DELEGATE_LIVE_FILE", None)
            replay: Any = self  # borrows Replay's fake CLI and launcher, which only need what Replay.setup_method sets
            return tss.Replay.launch(replay, kind, tss.Replay.fake(replay, kind, lines))

    def lines(self, path):
        return [json.loads(x) for x in Path(path).read_text().splitlines()]

    def events(self, path):
        return [e for e in self.lines(path) if "k" in e]  # the first line is the WorkerStarted, which has no kind

    @real_proc("delegate: a worker, git or CLI process")
    def test_codex(self):
        f = self.base / "sub" / "dir" / "live.jsonl"  # parent dirs are created
        r = self.run_kind("codex", CODEX, f)
        assert r.get("outcome") is None
        ev = self.events(f)
        assert [e["k"] for e in ev] == ["start", "cmd_start", "cmd_end", "tool_start", "tool_end", "think", "msg", "raw", "tokens", "end"]
        assert (ev[1]["id"], ev[2]["id"], ev[2]["exit"], ev[2]["out"]) == ("c1", "c1", 0, "a b")
        assert len(ev[1]["text"]) == 2000
        assert (ev[3]["id"], ev[3]["text"], ev[4]["id"]) == ("f1", "edit x.py", "f1")
        assert len(ev[5]["text"]) == 500
        assert ev[7] == {"t": ev[7]["t"], "k": "raw", "type": "weird.event"}  # the type name only, never the payload
        assert (ev[8]["in"], ev[8]["cached"], ev[8]["out"]) == (100, 40, 7)
        assert (ev[0]["harness"], ev[0]["role"], ev[0]["effort"], isinstance(ev[0]["pid"], int)) == ("codex", "worker", "high", True)
        first = self.lines(f)[0]
        assert (sorted(first), first["pid"] == ev[0]["pid"], first["pgid"], first["run_id"]) == (
            ["pgid", "pid", "run_id", "v"],
            True,
            first["pid"],
            "rid12345",
        )
        assert ev[-1]["status"] == "done"
        assert all(isinstance(e["t"], float) for e in ev)

    @real_proc("delegate: a worker, git or CLI process")
    def test_codex_lines_are_parsed_once_for_the_live_file_the_turn_and_the_evidence(self):
        f = self.base / "live.jsonl"
        real = CodexHarness.parse_line
        with mock.patch.object(CodexHarness, "parse_line", autospec=True, side_effect=real) as parse:
            r = self.run_kind("codex", CODEX, f)
        assert r.get("outcome") is None
        assert parse.call_count == len(CODEX)
        assert (r["tokens"], r["ref"]) == ({"in": 100, "cached": 40, "out": 7}, "th-1")
        assert self.events(f)[1]["k"] == "cmd_start"

    @real_proc("delegate: a worker, git or CLI process")
    def test_claude(self):
        f = self.base / "live.jsonl"
        assert self.run_kind("claude", CLAUDE, f).get("outcome") is None
        ev = self.events(f)
        assert [e["k"] for e in ev] == ["start", "cmd_start", "tool_start", "tokens", "cmd_end", "tool_end", "msg", "tokens", "end"]
        assert (ev[1]["id"], ev[1]["text"], ev[4]["id"], ev[4]["out"]) == ("tu1", "ls", "tu1", "a b")
        assert (ev[2]["id"], ev[2]["text"], ev[5]["id"], ev[5]["out"]) == ("tu2", "Edit skills/x.py", "tu2", "ok")
        assert ev[-1]["cost_usd"] == 0.25

    @real_proc("delegate: a worker, git or CLI process")
    def test_opencode(self):
        f = self.base / "live.jsonl"
        assert self.run_kind("opencode", OPENCODE, f).get("outcome") is None
        ev = self.events(f)
        assert [e["k"] for e in ev] == ["start", "cmd_start", "cmd_end", "tool_start", "tool_end", "tokens", "msg", "tokens", "end"]
        assert (ev[1]["id"], ev[2]["id"], ev[2]["exit"], ev[2]["secs"]) == ("o1", "o1", 0, 0.5)
        assert (ev[3]["text"], ev[3]["id"], ev[4]["id"]) == ("edit skills/x.py", "o2", "o2")

    @real_proc("delegate: a worker, git or CLI process")
    def test_env_unset_writes_nothing(self):
        for kind, lines in (("codex", CODEX), ("claude", CLAUDE), ("opencode", OPENCODE)):
            with self.subTest(kind):
                assert self.run_kind(kind, lines, None).get("outcome") is None
        assert [p.name for p in self.base.rglob("*.jsonl")] == []

    def test_a_stall_is_emitted_at_60_s_then_every_60_s(self):
        f = self.base / "live.jsonl"
        lv = LiveSink("codex", str(f))
        for idle in (10, 59, 61, 90, 119, 121, 130, 5, 70):
            lv.poll(idle)
        assert [e["secs"] for e in self.events(f)] == [61, 121, 70]

    def test_a_write_error_warns_once_and_never_raises(self):
        lv = LiveSink("codex", "/dev/null/nope/live.jsonl")
        with mock.patch("sys.stderr") as err:
            lv.message("a")
            lv.message("b")
        assert err.write.call_count == 2  # one print: text + newline
        assert lv.broken

    def test_a_live_file_stops_growing_at_the_cap_but_still_says_end(self):
        f = self.base / "live.jsonl"
        with mock.patch("delegate.app.publish.LIVE_FILE_MAX", 400):
            lv = LiveSink("codex", str(f))
            for _ in range(20):
                lv.message("x" * 50)
            lv.end("done")
        ev = self.events(f)
        assert (ev[-1]["k"], lv.capped, 0 < len(ev) < 10) == ("end", True, True)

    def test_end_status(self):
        assert [
            end_status(True, None, None, 0),
            end_status(False, "hung", None, 0),
            end_status(False, None, "stall", 0),
            end_status(False, None, "answer", -9),
            end_status(False, None, None, 0),
            end_status(False, None, None, 1),
        ] == ["timeout", "killed", "killed", "done", "done", "error"]
