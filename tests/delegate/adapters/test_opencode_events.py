"""OpenCodeHarness: golden `opencode run --format json --print-logs` streams (stdout events and stderr log lines) -> HarnessEvents +
Evidence + Summary, the provisional rows a permission line starts, its argv and sandboxed environment, the free-model check,
its login probe.
No real ZAI call is made here: the goldens are recorded shapes (87-live-view-design.md), not a live check."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from any_agent import events as ev
from any_agent import procs
from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses import opencode_sandbox as box
from any_agent.harnesses.opencode import OpenCodeHarness, Profile
from any_agent.protocol import LaunchInputs
from delegate.app import harnesses
from delegate.app.publish import LiveSink
from delegate.contracts.json_types import obj
from support.case import Case
from support.tmpdir import TemporaryDirectory

HERE = Path(__file__).resolve().parent

GOLD = HERE / "golden"


def lines(name):
    return (GOLD / name).read_text().splitlines()


def names(evs):
    return [type(e).__name__ for e in evs]


def only[T](evs: Sequence[object], kind: type[T], i: int = 0) -> T:
    """The i-th event, which must be a `kind`."""
    e = evs[i]
    assert isinstance(e, kind)
    return e


def replay(h, tick=None):
    """The log lines arrive first (a tool's permission line precedes its stdout event), then the stdout events."""
    got = [e for ln in lines("opencode_session.log") for e in h.parse_log_line(ln)]
    return got, [h.parse_line(x) for x in lines("opencode_session.jsonl")]


class Stream:
    def test_permission_lines_start_provisional_rows(self):
        h = OpenCodeHarness()
        got, _ = replay(h)
        assert [(type(e).__name__, e.id, e.prov) for e in got] == [("Cmd", "oc:1", True), ("Cmd", "oc:2", True), ("Tool", "oc:3", True)]
        assert (got[0].text, got[1].text, got[2].name, got[2].arg) == (
            "sleep 6",
            "echo done",
            "read",
            "a.py",
        )  # external_directory is not a tool

    def test_the_completed_call_closes_every_subcommand_row_and_gives_the_full_text(self):
        h = OpenCodeHarness()
        _, per_line = replay(h)
        bash = per_line[1]
        assert names(bash) == ["CmdEnd", "CmdEnd"]
        assert (bash[0].id, bash[0].text, bash[0].exit, bash[0].out, bash[0].secs) == ("oc:1", "sleep 6; echo done", 0, "done", None)
        assert (bash[1].id, bash[1].text) == ("oc:2", "echo done")
        read = per_line[2]
        assert (names(read), read[0].id, read[0].arg, read[0].secs) == (["ToolEnd"], "oc:3", "a.py", None)
        assert h.prov == []

    def test_a_call_with_no_permission_line_is_reported_whole(self):
        h = OpenCodeHarness()
        evs = [h.parse_line(x) for x in lines("opencode_session.jsonl")][1]
        end = only(evs, ev.CmdEnd)
        assert (names(evs), end.id, end.secs) == (["CmdEnd"], "o1", 6.0)

    def test_denials_are_typed_and_come_from_the_tool_output(self):
        h = OpenCodeHarness()
        per_line = [h.parse_line(x) for x in lines("opencode_session.jsonl")]
        assert names(per_line[3]) == ["CmdEnd", "Denied"]
        assert names(per_line[4]) == ["ToolEnd", "Denied"]
        assert [(d.tool, d.kind) for d in h.evidence.denials] == [("bash", "sandbox_limit"), ("edit", "policy")]
        assert only(per_line[4], ev.Denied, 1).input == {"filePath": "b.py"}
        assert only(per_line[3], ev.CmdEnd).exit == 1

    def test_steps_and_text_are_the_evidence(self):
        h = OpenCodeHarness()
        per_line = [h.parse_line(x) for x in lines("opencode_session.jsonl")]
        assert names(per_line[0]) == ["Started"]
        assert names(per_line[5]) == ["Tokens"]
        assert (only(per_line[6], ev.Msg).final, names(per_line[7])) == (False, ["TurnDone"])  # only the step that stops ends the turn
        e = h.evidence
        assert (e.ref, e.last, e.turns, e.tokens, e.context_k, e.work) == (
            "ses_1",
            "opencode answer",
            2,
            {"in": 38, "cached": 5, "out": 6},
            0.0,
            True,
        )

    def test_the_summary_folds_steps_into_the_accounting_record(self):
        h = OpenCodeHarness(Profile(price="catalog"))
        for x in lines("opencode_session.jsonl"):
            h.parse_line(x)
        s = h.summary(0, "", "stderr noise", "answer", False)
        assert (s.text, s.rc, s.vendor, s.stderr, s.stands, s.res["turns"], s.res["started"]) == (
            "opencode answer",
            0,
            "",
            "",
            True,
            2,
            True,
        )
        a = obj(s.res["acct"])
        assert (a["in_fresh"], a["cache_read"], a["cache_write"], a["out"], a["cost_usd"], a["cost_source"]) == (
            30,
            5,
            3,
            6,
            0.03,
            "harness",
        )
        assert s.res["cost"] == 0.03
        for price, want in (("free", (0.0, "free")), ("unknown", (None, "unknown"))):
            h2 = OpenCodeHarness(Profile(price=price))
            for x in lines("opencode_session.jsonl"):
                h2.parse_line(x)
            a2 = obj(h2.summary(0, "", "", None, False).res["acct"])
            assert (a2["cost_usd"], a2["cost_source"]) == want

    def test_an_error_event_is_the_vendors_words_and_stderr_after_our_own_kill_is_not(self):
        h = OpenCodeHarness()
        for x in lines("opencode_error.jsonl"):
            assert names(h.parse_line(x)) == ["Started", "HarnessError"]
        assert h.summary(1, "", "shell: killed", None, False).vendor == "Rate limit reached for requests, try again later"
        h = OpenCodeHarness()
        assert h.summary(-9, "", "shell: killed", "answer", False).vendor == ""
        assert h.summary(1, "", "shell: killed", None, False).vendor == "shell: killed"

    def test_a_log_line_that_quotes_a_limit_phrase_is_a_tool_not_a_throttle(self):
        h = OpenCodeHarness()
        line = 'INFO  2026-10-26T21:32:01 +3ms service=permission evaluated permission=bash pattern="cat <<EOF\\ntry again later\\nEOF"'
        got = h.parse_log_line(line + " action=allow")
        assert (names(got), only(got, ev.Cmd).text) == (["Cmd"], "cat <<EOF\ntry again later\nEOF")
        assert h.parse_log_line("ERROR service=llm error=Rate limit reached") == []

    def test_provisional_rows_reach_the_live_file_seconds_before_the_end(self):
        """A permission line 4 s before the completed tool_use: cmd_start with prov, then cmd_end with the full text and secs >= 4."""
        h, clock = OpenCodeHarness(), [100.0]
        with TemporaryDirectory() as d:
            sink = LiveSink("opencode", str(Path(d) / "l.jsonl"), wall=lambda: clock[0], run_id="r")
            sink.start(lane="ZAI_CODING_SUBSCRIPTION", model="m", effort="high", role="worker")
            for e in h.parse_log_line(lines("opencode_session.log")[1]):
                sink.feed(e)
            clock[0] = 104.5
            for e in h.parse_line(lines("opencode_session.jsonl")[1]):
                sink.feed(e)
            sink.end("done")
            rows = [json.loads(x) for x in (Path(d) / "l.jsonl").read_text().splitlines()]
        start, end = rows[0], rows[1]
        assert (start["k"], start["id"], start["text"], start.get("prov")) == ("cmd_start", "oc:1", "sleep 6", True)
        assert (end["k"], end["id"], end["secs"], end["exit"], end["out"]) == ("cmd_end", "oc:1", 4.5, 0, "done")
        assert (end["t"] - start["t"]) >= 4

    def test_a_line_that_is_not_json_or_an_object_yields_nothing(self):
        assert [OpenCodeHarness().parse_line(x) for x in ("", "oops", "[1]")] == ([[]] * 3)


class World(Case):
    def spec(self, profile=None, **kw):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        h = OpenCodeHarness(profile, Path(tmp.name))
        with mock.patch.object(opencode_sandbox, "write_shell") as shell:
            s = h.launch_spec(
                LaunchInputs(
                    exe="/bin/oc",
                    cwd="/w",
                    model="m",
                    effort="high",
                    prompt="rules\n\nbrief",
                    env={"A": "1", "OPENCODE_AUTH_JSON": "x"},
                    session="rid12345",
                    **kw,
                )
            )
        return h, s, shell, tmp.name

    def test_a_fresh_launch_prints_logs_and_runs_in_a_config_root_of_its_own(self):
        _h, s, shell, root = self.spec()
        assert s.argv == [
            "/bin/oc",
            "run",
            "--pure",
            "--format",
            "json",
            "--print-logs",
            "--log-level",
            "INFO",
            "-m",
            "m",
            "--variant",
            "high",
            "--dir",
            "/w",
        ]
        assert (s.stdin, s.cwd, s.env["A"], s.env["XDG_CONFIG_HOME"], s.env["OPENCODE_DISABLE_PROJECT_CONFIG"]) == (
            "rules\n\nbrief",
            "/w",
            "1",
            root + "/opencode-home",
            "1",
        )
        assert s.env["SHELL"] == (root + "/opencode-shell-rid12345.sh")
        shell.assert_called_once()
        assert json.loads(s.env["OPENCODE_CONFIG_CONTENT"])["permission"]["task"] == "deny"
        assert "OPENCODE_AUTH_JSON" in s.env  # an unpinned lane keeps the login it runs on

    def test_a_pinned_lane_drops_credential_overrides_and_enables_one_provider(self):
        _, s, _, root = self.spec(Profile(providers=("zai-coding-plan",), own_data=True))
        assert "OPENCODE_AUTH_JSON" not in s.env
        assert json.loads(s.env["OPENCODE_CONFIG_CONTENT"])["enabled_providers"] == ["zai-coding-plan"]
        assert s.env["XDG_DATA_HOME"] == (root + "/opencode-free-data")

    def test_a_resume_names_the_session(self):
        h, s, _, _ = self.spec(resume="ses_9")
        assert s.argv[-2:] == ["--session", "ses_9"]
        assert h.evidence.ref == "ses_9"

    def free(self, out, model="opencode/deepseek-v4.1-flash-free"):
        h = OpenCodeHarness()
        h.exe = "opencode"
        with mock.patch.object(procs, "run_capture", return_value=subprocess.CompletedProcess([], 0, out, "")):
            return h.free_model_ok(model, {})

    def test_the_free_model_is_accepted_only_exact_and_zero_priced(self):
        def cat(**c):
            return "opencode/deepseek-v4.1-flash-free\n" + json.dumps(
                dict(
                    {
                        "id": "deepseek-v4.1-flash-free",
                        "providerID": "opencode",
                        "status": "active",
                        "cost": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
                    },
                    **c,
                )
            )

        assert self.free(cat())
        assert not self.free(cat(), "deepseek/deepseek-chat")
        for out in (
            "",
            "not-json",
            cat(status="deprecated"),
            cat(cost={"input": 0, "output": 1, "cache": {"read": 0, "write": 0}}),
            cat(cost={"input": 0, "output": 0}),
            cat(cost={"input": False, "output": 0, "cache": {"read": 0, "write": 0}}),
        ):
            assert not self.free(out), out
        h = OpenCodeHarness()
        with mock.patch.object(procs, "run_capture", side_effect=subprocess.TimeoutExpired("opencode", 30)):
            assert not h.free_model_ok("opencode/deepseek-v4.1-flash-free", {})

    def test_the_login_probe_reads_the_auth_file(self):
        with (
            TemporaryDirectory() as d,
            mock.patch.dict("os.environ", {"XDG_DATA_HOME": d}),
            mock.patch.object(OpenCodeHarness, "find_exe", return_value="oc"),
        ):
            p = Path(d) / "opencode" / "auth.json"
            p.parent.mkdir()
            zai = OpenCodeHarness(Profile(auth_key="zai-coding-plan", need_key=True))
            for auth, want in (
                ({"zai": {"type": "api", "key": "k"}}, False),
                ({"zai-coding-plan": {}}, False),
                ({"zai-coding-plan": {"type": "api", "key": "k"}}, True),
            ):
                p.write_text(json.dumps(auth))
                assert zai.login_probe(5)[0] == want
            assert OpenCodeHarness(Profile()).login_probe(5)[0] is True  # free access needs no login
            with mock.patch.object(OpenCodeHarness, "find_exe", return_value=None):
                assert zai.login_probe(5)[0] is None

    def test_the_sandbox_shell_is_offline_and_a_refused_network_is_not_a_denial(self):
        assert box.network_refusal("error: tcp connect error\n  Operation not permitted (os error 1)")
        assert not box.network_refusal("cat: /Users/x/.ssh/id_rsa: Operation not permitted")
        assert box.permissions(harnesses.sandbox(), True)["external_directory"] == "deny"
        assert obj(box.permissions(harnesses.sandbox(), False)["read"])[str(Path.home() / ".ssh")] == "deny"
