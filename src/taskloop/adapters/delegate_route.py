"""`Delegate` over `route.py run`: temp files for the brief and schema, the live file tailed while the child runs."""
import dataclasses
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from taskloop.adapters import delegate_wire
from taskloop.adapters.proc import run_group
from taskloop.contracts import codec
from taskloop.contracts.delegate import LIVE_EVENT, DelegateResult, RunRequest
from taskloop.contracts.jsonl import Jsonl
from taskloop.contracts.ports import EventSink

LIVE_ENV = "DELEGATE_LIVE_FILE"
BACKSTOP_S = 120.0  # the default grace past `timeout_s` before the engine stops route.py itself


class LiveTail:
    """Reads a live file by byte cursor and hands each decoded event on; the first line (`WorkerStarted`) and lines that are no
    event of ours are passed over."""

    def __init__(self, path: Path, sink: EventSink | None) -> None:
        self.file, self.sink, self.cursor = Jsonl(path), sink, 0

    def drain(self) -> None:
        entries, self.cursor = self.file.read_from(self.cursor)
        for e in entries:
            if self.sink is None or "kind" not in e.data:
                continue
            try:
                self.sink(codec.from_tagged(LIVE_EVENT, e.data))
            except codec.CodecError:
                pass


class RouteDelegate:
    def __init__(self, route: str, python: str = sys.executable, env: Mapping[str, str] | None = None,
                 timeout_s: float = 3600.0, backstop_s: float = BACKSTOP_S) -> None:
        self.route, self.python, self.env, self.timeout_s, self.backstop_s = route, python, dict(env or {}), timeout_s, backstop_s

    def _env(self, extra: Mapping[str, str]) -> dict[str, str]:
        return dict(os.environ, **self.env, **extra)

    def speaks(self) -> int:
        ran = run_group([self.python, self.route, "contract", "--json"], None, self._env({}), 60.0)
        try:
            n = json.loads(ran.out.strip().splitlines()[-1]).get("contract")
        except (ValueError, IndexError, AttributeError):
            return 0
        return n if isinstance(n, int) else 0

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        with tempfile.TemporaryDirectory() as d:
            brief_path, schema_path, live = Path(d, "brief.md"), Path(d, "schema.json"), Path(d, "live.jsonl")
            brief_path.write_text(brief, encoding="utf-8")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            call = dataclasses.replace(req, brief_path=str(brief_path), schema_path=str(schema_path))
            tail = LiveTail(live, on_event)
            ran = run_group(call.to_argv(self.python, self.route), req.cwd or None, self._env({LIVE_ENV: str(live)}),
                            self.timeout_s + self.backstop_s, tail.drain)
        if ran.timed_out:
            return delegate_wire.synth("timeout", "bead", "transient", "the engine stopped route.py at its backstop", req.resume)
        try:
            answer: Any = json.loads(ran.out.strip().splitlines()[-1]) if ran.out.strip() else None
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            return delegate_wire.synth("crash", "machine", "needs_owner",
                                       "route.py exit %d, no answer object: %s" % (ran.exit, (ran.out or ran.err)[-1500:]), req.resume)
        return delegate_wire.result_of(answer)
