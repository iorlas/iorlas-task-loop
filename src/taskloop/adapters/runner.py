"""The process seam of an engine delegate call: `route.py run` through stream-proc, stderr to the engine's log, the live file watched.

`StreamRunner` is one per call. Its `stop` and `obs` say how the call ended (why it was stopped, which pids outlived the stop, the
process boundaries); `worker` is the live file's first line (`WorkerStarted`), read while the call runs, never from stderr or `ps`.
Silence is delegate's (`--idle`, its own watchdog, a typed stop in the answer); the engine keeps no silence timer. A call that ends
by itself returns a `CompletedProcess`-like; one the engine ends raises `Stopped`."""

import contextlib
import json
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, override

import stream_proc

from taskloop.adapters import procs
from taskloop.adapters.delegate import Stopped
from taskloop.contracts import wire
from taskloop.contracts.delegate import LiveEvent, LiveStart, WorkerStarted

POLL_S = 0.5  # seconds between the looks at the live file while a call runs


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


def live_path(log_path: str | Path, n: int, step: str) -> str:
    """Where delegate appends the worker's live events for call n of a run: <engine log without .jsonl>.live/<NN>-<step>.jsonl."""
    base = str(log_path)
    base = base[: -len(".jsonl")] if base.endswith(".jsonl") else base
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", step or "call").strip("-") or "call"
    return f"{base}.live/{n:02d}-{slug}.jsonl"


def mtime(path: str | Path) -> float | None:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


Completed = subprocess.CompletedProcess[str]  # what a seam call answers


def completed(cmd: Sequence[str], code: int, out: str, err: str = "") -> Completed:
    return subprocess.CompletedProcess(cmd, code, out, err)


class Seam:
    """What the engine reads off a process seam after a call (stop, obs, secs, worker, live_start): a fake lane's defaults."""

    def __init__(self) -> None:
        self.stop: dict[str, Any] = {}
        self.obs: dict[str, Any] = {}
        self.secs = 0.0
        self.worker: WorkerStarted | None = None
        self.outer: threading.Event | None = None  # the run's stop flag: set, the call is stopped

    def live_start(self) -> LiveStart | None:
        return None


class StreamRunner(Seam):
    def __init__(
        self,
        log_path: str | Path,
        wall: float | None = None,
        live: str = "",
        on_worker: Callable[[WorkerStarted], None] | None = None,
        grace: float = procs.STOP_GRACE_S,
    ) -> None:
        super().__init__()
        self.log_path, self.wall, self.live, self.on_worker, self.grace = log_path, wall, live, on_worker, grace

    @override
    def live_start(self) -> LiveStart | None:
        """The harness, lane and model the call ran on, from the live file's `start` event."""
        return worker_start(self.live) if self.live else None

    def watch(self, done: threading.Event, halt: threading.Event, live: str) -> None:
        """While the call runs: note the worker the live file names, and stop the call when the run is stopped."""
        while not done.wait(POLL_S):
            if self.outer is not None and self.outer.is_set():
                self.obs.update(kill_t=time.time(), why="interrupted")
                halt.set()
                return
            if self.worker is None and live:
                self.worker = worker_started(live)
                if self.worker and self.on_worker:
                    self.on_worker(self.worker)

    def __call__(
        self, cmd: Sequence[str], cwd: str | None = None, env: dict[str, str] | None = None, timeout: float | None = None, **_: Any
    ) -> subprocess.CompletedProcess[str]:
        live = self.live or (env or {}).get("DELEGATE_LIVE_FILE", "")
        t0 = time.time()
        self.obs.update(started_t=t0, ended_t=None, first_error_t=None, last_event_t=None, kill_t=None, why="", alive=[])
        self.stop.clear()
        self.worker = None
        out: list[str] = []
        done, halt = threading.Event(), threading.Event()

        def seen(text: str, keep: bool, log: Any = None) -> None:
            if self.obs["kill_t"] is None:
                self.obs["last_event_t"] = time.time()  # frozen at the stop: shutdown output never moves the boundary
            if keep:
                out.append(text)
            if log is not None:
                with contextlib.suppress(ValueError, OSError):  # the call is over and its log closed
                    log.write(text.encode("utf-8", "replace"))
                    log.flush()

        helper = threading.Thread(target=self.watch, args=(done, halt, live), daemon=True)
        helper.start()
        try:
            with open(self.log_path, "ab") as log:
                res = stream_proc.run(
                    list(cmd),
                    cwd=cwd,
                    env=env,
                    on_stdout=lambda s: seen(s, True),
                    on_stderr=lambda s: seen(s, False, log),
                    timeout=self.wall or timeout or 3600.0,
                    stop=halt,
                    grace=self.grace,
                )
        except BaseException:  # stopped (a raising SIGTERM handler): stream-proc stopped the tree before this
            self.obs.update(kill_t=self.obs["kill_t"] or time.time(), why=self.obs["why"] or "interrupted", ended_t=time.time())
            self.stop.update(self.obs)
            raise
        finally:
            done.set()
            helper.join(2)
        self.secs, self.obs["ended_t"] = res.secs, time.time()
        if self.worker is None and live:
            self.worker = worker_started(live)
        if res.timed_out:
            self.obs.update(
                kill_t=self.obs["kill_t"] or time.time(),
                why=self.obs["why"] or f"timeout {int((self.wall or timeout or 3600) // 60)} min",
                alive=list(res.survivors),
            )
            self.stop.update(self.obs, kind=res.timed_out)
            raise Stopped(self.obs["why"])
        return subprocess.CompletedProcess(
            list(cmd), res.returncode if res.returncode is not None else -(res.signal or 1), "".join(out), ""
        )
