"""CodexHarness: golden event streams (real `codex exec --json` lines from the delegate fixtures) -> HarnessEvents + Evidence -> live lines.
Regenerate a golden with
`PYTHONPATH=src:tests:tests/delegate uv run python tests/delegate/adapters/test_codex_events.py --regen` after reading the diff."""

import dataclasses
import itertools
import json
import os
import stat
import sys
from pathlib import Path
from unittest import mock

from any_agent.harnesses.codex import CodexHarness
from delegate.app.publish import LiveSink
from support.procsim import real_proc
from support.tmpdir import TemporaryDirectory

HERE = Path(__file__).resolve().parent.parent

GOLDEN = HERE / "golden"
NAMES = sorted(p.name[len("codex_") : -len(".jsonl")] for p in GOLDEN.glob("codex_*.jsonl"))


def lines_of(name):
    return (GOLDEN / f"codex_{name}.jsonl").read_text().splitlines()


def parse(name):
    h = CodexHarness(clock=lambda: 5.0)
    return h, [h.parse_line(line) for line in lines_of(name)]


def as_json(h, per_line):
    return {
        "events": [[dict(event=type(e).__name__, **dataclasses.asdict(e)) for e in evs] for evs in per_line],
        "evidence": dataclasses.asdict(h.evidence),
    }


def live_lines(per_line, path):
    tick = itertools.count(100)
    sink = LiveSink("codex", str(path), wall=lambda: float(next(tick)), run_id="rid")
    sink.start(lane="OPENAI_SUBSCRIPTION", model="m", effort="high", role="worker")
    sink.started(4242)
    for evs in per_line:
        for e in evs:
            sink.feed(e)
    sink.end("done")
    return [json.loads(x) for x in Path(path).read_text().splitlines()]






INPUTS = {
    "exe": "/bin/codex",
    "cwd": "/w",
    "model": "gpt",
    "effort": "high",
    "sandbox": "read-only",
    "prompt": "rules\n\nbrief",
    "out_file": "/c/last.txt",
    "env": {"A": "1"},
    "cli": ["codex", "exec", "-C", "/w", "-s", "read-only", "-m", "gpt", "--skip-git-repo-check"],
    "access": ["--ignore-rules"],
    "isolation": ["-c", "skills.config=[]"],
}


class World:



    @real_proc("delegate: a worker, git or CLI process")
    def test_the_login_probe_runs_the_status_command(self):
        with TemporaryDirectory() as d:
            exe = Path(d) / "codex"
            exe.write_text('#!/bin/sh\n[ "$FAKE_LOGIN" = out ] && { echo "Not logged in" >&2; exit 1; }\necho "Logged in using ChatGPT"\n')
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"PATH": d}):
                assert CodexHarness().login_probe(5) == (True, "Logged in using ChatGPT")
                with mock.patch.dict(os.environ, {"FAKE_LOGIN": "out"}):
                    assert CodexHarness().login_probe(5) == (False, "Not logged in")
            with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
                assert CodexHarness().login_probe(5)[0] is None


if __name__ == "__main__" and "--regen" in sys.argv:
    for n in NAMES:
        h, pl = parse(n)
        (GOLDEN / f"codex_{n}.expected.json").write_text(json.dumps(as_json(h, pl), indent=1) + "\n")
        with TemporaryDirectory() as d:
            (GOLDEN / f"codex_{n}.live.json").write_text(json.dumps(live_lines(pl, Path(d) / "l.jsonl"), indent=1) + "\n")
