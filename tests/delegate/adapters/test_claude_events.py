"""ClaudeHarness: golden `claude -p --output-format stream-json` streams -> HarnessEvents + Evidence + Summary,
its argv and its login probe."""

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

from delegate.adapters.harness.base import LaunchInputs
from delegate.adapters.harness.claude import ClaudeHarness, stream_usage, tokens_of
from delegate.contracts import events as ev
from delegate.contracts.json_types import obj
from support.procsim import real_proc

HERE = Path(__file__).resolve().parent


def stream(name):
    h = ClaudeHarness()
    return h, [h.parse_line(x) for x in (HERE / "golden" / f"claude_{name}.jsonl").read_text().splitlines()]


def kinds(per_line):
    return [[type(e).__name__ for e in evs] for evs in per_line]


class Stream:
    def test_a_session_becomes_one_event_per_fact(self):
        _h, pl = stream("session")
        assert kinds(pl) == [
            [],
            [],
            ["Msg", "Cmd", "Tool", "Cmd", "Tokens"],
            ["CmdEnd", "ToolEnd", "CmdEnd"],
            ["Think", "Msg", "Tokens"],
            ["TurnDone", "Denied"],
            [],
        ]
        text, cmd, tool, _push, tokens = pl[2]
        assert (text.final, cmd.id, cmd.text, cmd.cwd, tool.name, tool.arg) == (False, "tu1", "ls", "/w", "Edit", "x.py")
        assert (tokens.in_, tokens.cached, tokens.out, tokens.cache_write) == (55, 40, 2, 5)
        end, tend, pend = pl[3]
        assert (end.id, end.exit, end.out, tend.out, pend.exit) == ("tu1", None, "a b", "ok", 1)
        assert pl[4][1].final
        assert pl[5][1] == ev.Denied(tool="Bash", input={"command": "git push"}, reason="the CLI's permission check refused the call")

    def test_evidence_holds_what_the_stream_established(self):
        h, _ = stream("session")
        e = h.evidence
        assert (e.work, e.last, e.turns, obj(e.final)["session_id"], e.context_k, len(e.steps), e.denials[0].tool) == (
            True,
            "all done",
            2,
            "sess-1",
            0.1,
            2,
            "Bash",
        )
        assert obj(e.final)["result"] == "all done"  # the second result is another turn after background tasks: the first one is the answer

    def test_the_summary_of_a_done_run(self):
        h, _ = stream("session")
        s = h.summary(0, "", "", "answer", False)
        assert (s.text, s.rc, s.check, s.vendor, s.cost, s.warnings, s.work) == ("all done", 0, False, "", 0.25, [], True)
        assert (s.res["ref"], s.res["tokens"], s.res["turns"], s.res["context_k"]) == (
            "sess-1",
            {"in": 120, "cached": 100, "out": 9},
            2,
            0.1,
        )
        acct = obj(s.res["acct"])
        assert (acct["cost_usd"], acct["ttl_s"]) == (0.25, 3600)

    def test_an_api_error_result_is_the_clis_words(self):
        h, _ = stream("api_error")
        s = h.summary(1, "", "boom", None, False)
        assert (s.rc, s.check, s.vendor, s.stderr) == (1, True, "API Error: 429 rate limit exceeded", "boom")
        assert h.vendor_error(1) == s.vendor

    def test_the_models_own_words_are_not_the_vendors(self):
        for j in (
            {"is_error": True, "result": "I added rate limit handling; quota tests fail with 429"},
            {"is_error": False, "result": "API Error: shown by the task itself"},
        ):
            h = ClaudeHarness()
            h.parse_line(json.dumps(dict(j, type="result")))
            assert h.vendor_error(1) == ""

    def test_no_result_event_folds_the_requests_and_a_final_message_is_the_answer(self):
        h = ClaudeHarness()
        for line in (HERE / "golden" / "claude_session.jsonl").read_text().splitlines()[:5]:
            h.parse_line(line)
        s = h.summary(-9, "", "", "answer", False)
        assert (s.text, s.rc, s.warnings, s.res["tokens"]) == (
            "all done",
            0,
            ["answer_done_process_alive"],
            {"in": 120, "cached": 100, "out": 9},
        )
        assert stream_usage([{"input_tokens": 1, "output_tokens": 2}, {"input_tokens": 3, "cache_read_input_tokens": 9}]) == {
            "input_tokens": 4,
            "cache_read_input_tokens": 9,
            "cache_creation_input_tokens": 0,
            "output_tokens": 2,
        }
        assert (stream_usage([]), tokens_of({})) == ({}, None)

    def test_an_answer_then_a_dropped_connection_is_done_with_a_note(self):
        h, _ = stream("session")
        assert h.summary(1, "", "error sending request for url", None, False).warnings == ["net_after_answer"]

    def test_a_line_that_is_not_json_or_an_object_yields_nothing(self):
        assert [ClaudeHarness().parse_line(x) for x in ("", "oops", "[1]")] == ([[]] * 3)

    def test_an_unknown_event_is_named_never_quoted(self):
        assert ClaudeHarness().parse_line(json.dumps({"type": "weird", "payload": "secret"})) == [ev.Unknown(type="weird")]


INPUTS = {
    "exe": "/bin/claude",
    "cwd": "/w",
    "model": "m",
    "effort": "high",
    "prompt": "brief",
    "env": {"A": "1"},
    "session": "rid",
    "system": "rules",
    "settings": "{}",
}


class World:
    def test_a_fresh_read_only_launch(self):
        s = ClaudeHarness().launch_spec(LaunchInputs(**INPUTS))
        assert s.argv[:11] == [
            "/bin/claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            "m",
            "--effort",
            "high",
            "--session-id",
            "rid",
        ]
        assert s.argv[s.argv.index("--tools") + 1] == "Read,Glob,Grep,Bash"
        assert (s.stdin, s.cwd, s.env, "--max-budget-usd" in s.argv, "--json-schema" in s.argv) == ("brief", "/w", {"A": "1"}, False, False)

    def test_a_resumed_write_launch_with_a_schema(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.json").write_text('{"type": "object"}')
            h = ClaudeHarness()
            s = h.launch_spec(LaunchInputs(**INPUTS, write=True, resume="old", schema=str(Path(d) / "s.json")))
        assert s.argv[s.argv.index("--resume") + 1] == "old"
        assert "--session-id" not in s.argv
        assert (s.argv[s.argv.index("--tools") + 1], "--max-budget-usd" in s.argv, s.argv[-1]) == (
            "Read,Glob,Grep,Edit,Write,Bash",
            False,
            '{"type": "object"}',
        )
        assert h.evidence.ref == "old"

    def test_the_transcript_is_the_session_file(self):
        day = Path.home() / ".claude" / "projects" / "-w"
        day.mkdir(parents=True)
        (day / "sess-1.jsonl").write_text("{}\n")
        h = ClaudeHarness()
        assert (h.transcript("sess-1"), h.transcript("zzz"), h.transcript(None)) == (str(day / "sess-1.jsonl"), None, None)

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_login_probe_reads_auth_status(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "claude"
            exe.write_text("#!/bin/sh\necho '{\"loggedIn\": '$FAKE_IN'}'\n")
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"PATH": d, "FAKE_IN": "true"}):
                assert ClaudeHarness().login_probe(5)[0]
            with mock.patch.dict(os.environ, {"PATH": d, "FAKE_IN": "false"}):
                assert not ClaudeHarness().login_probe(5)[0]
            with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
                assert ClaudeHarness().login_probe(5)[0] is None
