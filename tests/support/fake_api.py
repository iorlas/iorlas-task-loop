"""A stand-in for `delegate.api.run` that starts a real shell worker in its own session, for the runner tests that need a process.

`FakeApi(workdir, body)` patches the runner's `api.run` (and `api.as_json`, the identity on the answer dict): the worker runs `body`
(a shell script) in `workdir`, the live file gets `WorkerStarted` as its first line like delegate's, and `started` receives the Handle.
`api.cancel` stays real: it stops the worker's process group. The answer is a done answer of fake_route."""
import contextlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from stream_proc import proc_start

from taskloop.adapters import runner
from tltestkit import fake_route


class FakeApi:
    def __init__(self, workdir: Path, body: str, chat_until: float = 0.0, answer: dict[str, Any] | None = None) -> None:
        self.dir, self.body, self.chat_until = workdir, body, chat_until
        self.answer = answer or fake_route.answer(fake_route.contract(), None, "r", False, {})
        self.requests: list[Any] = []
        self.pid = 0

    def run(self, request: Any, started: Callable[[Any], None] | None = None) -> dict[str, Any]:
        self.requests.append(request)
        worker = subprocess.Popen(["sh", "-c", self.body], cwd=self.dir, start_new_session=True)
        self.pid = worker.pid
        (self.dir / "w.pid").write_text(str(worker.pid))
        live = request.live_file
        if live:
            os.makedirs(os.path.dirname(live), exist_ok=True)
            with open(live, "a") as f:
                f.write(json.dumps({"v": 1, "pid": worker.pid, "pgid": worker.pid, "run_id": "run1"}) + "\n")
                f.flush()
                while time.time() < self.chat_until:
                    f.write(json.dumps({"t": time.time(), "k": "msg", "text": "still here"}) + "\n")
                    f.flush()
                    time.sleep(0.1)
        if started:
            started(runner.api.Handle(run_id="run1", pid=worker.pid, pgid=worker.pid, start=proc_start(worker.pid)))
        worker.wait()
        return self.answer

    def patch(self) -> contextlib.ExitStack:
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(runner.api, "run", self.run))
        stack.enter_context(mock.patch.object(runner.api, "as_json", lambda answer: answer))
        return stack
