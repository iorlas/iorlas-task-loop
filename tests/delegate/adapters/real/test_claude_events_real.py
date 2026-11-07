"""ClaudeHarness: golden `claude -p --output-format stream-json` streams -> HarnessEvents + Evidence + Summary,
its argv and its login probe."""

import os
import stat
from pathlib import Path
from unittest import mock

from any_agent.harnesses.claude import ClaudeHarness
from support.procsim import real_proc

from tltestkit.tmpdir import TemporaryDirectory

HERE = Path(__file__).resolve().parent.parent


def stream(name):
    h = ClaudeHarness()
    return h, [h.parse_line(x) for x in (HERE / "golden" / f"claude_{name}.jsonl").read_text().splitlines()]


def kinds(per_line):
    return [[type(e).__name__ for e in evs] for evs in per_line]




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



    @real_proc("delegate: a worker, git or CLI process")
    def test_the_login_probe_reads_auth_status(self):
        with TemporaryDirectory() as d:
            exe = Path(d) / "claude"
            exe.write_text("#!/bin/sh\necho '{\"loggedIn\": '$FAKE_IN'}'\n")
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"PATH": d, "FAKE_IN": "true"}):
                assert ClaudeHarness().login_probe(5)[0]
            with mock.patch.dict(os.environ, {"PATH": d, "FAKE_IN": "false"}):
                assert not ClaudeHarness().login_probe(5)[0]
            with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
                assert ClaudeHarness().login_probe(5)[0] is None
