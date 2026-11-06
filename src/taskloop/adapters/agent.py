"""`ApiAgent`: the `Agent` of `delegate.api`. `api.run` on a thread of its own; the Handle and `api.cancel` stay in here."""
import contextlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Self

from delegate import api
from taskloop.adapters import procs
from taskloop.contracts import wire
from taskloop.contracts.delegate import LiveEvent, LiveStart, WorkerStarted


def running_for(task: str) -> list[str]:
    """The runs delegate says still go for this task (the ids): a worker that outlived its engine. None when there is no task or delegate
    cannot say."""
    if not task:
        return []
    try:
        return [a.run_id for a in api.agents() if a.task == task]
    except (Exception, SystemExit):
        return []


def live_lines(path: str | Path) -> list[dict[str, Any]]:
    """The objects of a live file, in order; a torn last line and lines that are no object are passed over."""
    out: list[dict[str, Any]] = []
    try:
        with open(path, "rb") as f:
            for raw in f:
                with contextlib.suppress(ValueError):
                    j = json.loads(raw)
                    if isinstance(j, dict):
                        out.append(j)
    except OSError:
        pass
    return out


def worker_started(path: str | Path) -> WorkerStarted | None:
    """The first line of the live file, when it is a `WorkerStarted`."""
    lines = live_lines(path)[:1]
    if lines and "k" not in lines[0]:
        with contextlib.suppress(ValueError):
            return wire.load(WorkerStarted, lines[0])
    return None


def live_event(j: dict[str, Any]) -> Any:
    """The typed event of a live-file line (`k` names the kind; the file carries no `v`). ValueError for a kind we do not know."""
    return wire.load(LiveEvent, dict({a: b for a, b in j.items() if a != "k"}, kind=j.get("k"), v=1))


def worker_start(path: str | Path) -> LiveStart | None:
    """The first `start` event of the live file: the harness, lane, model and effort the call ran on."""
    for j in live_lines(path):
        if j.get("k") == "start":
            with contextlib.suppress(ValueError):
                return live_event(j)
    return None


def live_path(live_dir: str | Path, n: int, step: str) -> str:
    """Where delegate appends the worker's live events for call n of a run: <the run's live folder>/<NN>-<step>.jsonl."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", step or "call").strip("-") or "call"
    return f"{live_dir}/{n:02d}-{slug}.jsonl"


def new_live(live_dir: str | Path, n: int, step: str) -> str:
    """The live file for call n of a run, its folder made; "" when the folder cannot be made (the call then runs without one)."""
    path = live_path(live_dir, n, step)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return ""
    return path


def last_event_t(path: str | Path) -> float:
    """When the worker last wrote to its live file; 0 when there is none."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


class ApiAgent:
    def __init__(self, request: api.RunRequest, grace: float = procs.STOP_GRACE_S, live: str = "") -> None:
        self.request, self.grace = request, grace
        self.live = live or request.live_file or ""  # the file delegate appends the worker's events to: read in here only
        self._handles: list[api.Handle] = []
        self._box: list[api.RunResult] = []
        self._finished = threading.Event()
        self._thread = threading.Thread(target=self._work, daemon=True)

    def start(self) -> Self:
        self._thread.start()
        return self

    def _work(self) -> None:
        try:
            self._box.append(api.run(self.request, started=self._handles.append))
        finally:
            self._finished.set()

    def done(self, timeout: float) -> bool:
        return self._finished.wait(timeout)

    def result(self) -> dict[str, object]:
        if not self._box:
            raise ValueError("the call has no answer")
        return dict(api.as_json(self._box[0]))

    def stop(self) -> list[int]:
        """SIGTERM, then SIGKILL after the grace, then the wait for the call's thread. -> the survivors' pids."""
        alive: list[int] = []
        if self._handles:
            alive = [x.pid for x in api.cancel(self._handles[0]).survivors]
        self._thread.join(self.grace + 10)
        return alive

    def worker(self) -> WorkerStarted | None:
        """The worker delegate launched (the live file's first line); None until it exists."""
        return worker_started(self.live) if self.live else None

    def start_event(self) -> LiveStart | None:
        """The harness, lane, model and effort the call ran on (the live file's `start` event)."""
        return worker_start(self.live) if self.live else None

    def events(self) -> list[LiveEvent]:
        """The worker's events so far, in order (kinds this engine does not know are passed over)."""
        out: list[LiveEvent] = []
        for j in live_lines(self.live) if self.live else []:
            if "k" in j:
                with contextlib.suppress(ValueError):
                    out.append(live_event(j))
        return out
