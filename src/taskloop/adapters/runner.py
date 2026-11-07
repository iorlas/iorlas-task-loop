"""The process seam of an engine delegate call: one `delegate.api.run` thread, stderr to the engine's log, the live file watched.

`StreamRunner` is one per call. Its `stop` and `obs` say how the call ended (why it was stopped, which pids outlived the stop, the
process boundaries); `worker` is the live file's first line (`WorkerStarted`), read while the call runs, never from stderr or `ps`.
Silence is delegate's (`--idle`, its own watchdog, a typed stop in the answer); the engine keeps no silence timer. A call that ends
by itself returns a `CompletedProcess`-like; one the engine ends raises `Stopped`."""

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, override

from delegate import api
from taskloop.adapters import deadline, procs
from taskloop.adapters.agent import ApiAgent
from tlkernel.agent import Agent
from tlkernel.delegate import LiveStart, WorkerStarted
from tlkernel.delegateport import Seam, Stopped

POLL_S = 0.5  # seconds between the looks at the live file while a call runs


class ApiRunner(Seam):
    """The real seam: `delegate.api.run` on a thread of its own. The engine's stop flag, its wall limit and the deadline end the call by
    `api.cancel` on the worker's handle; the call then raises `Stopped`."""

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
        self.agent: Agent | None = None

    @override
    def live_start(self) -> LiveStart | None:
        """The harness, lane and model the call ran on, from the live file's `start` event."""
        return self.agent.start_event() if self.agent else None

    def __call__(
        self,
        cmd: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        request: api.RunRequest | None = None,
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        if request is None:
            raise ValueError("ApiRunner needs the delegate.api request")
        live = self.live or request.live_file or ""
        t0 = time.time()
        self.obs.update(started_t=t0, ended_t=None, first_error_t=None, last_event_t=None, kill_t=None, why="", alive=[])
        self.stop.clear()
        self.worker = None
        agent: Agent = ApiAgent(request, self.grace, live).start()
        self.agent = agent
        limit = deadline.remaining(self.wall or timeout or 3600.0)
        why = ""
        try:
            while not agent.done(POLL_S):
                if self.worker is None and live:
                    self.worker = agent.worker()
                    if self.worker and self.on_worker:
                        self.on_worker(self.worker)
                if self.outer is not None and self.outer.is_set():
                    why = "interrupted"
                elif time.time() - t0 >= limit:
                    why = f"timeout {int((self.wall or timeout or 3600) // 60)} min"
                if why:
                    self._cancel(agent, why)
                    break
        except BaseException:  # the engine itself is stopped (a raising SIGTERM handler): end the worker's tree first
            self.obs.update(kill_t=self.obs["kill_t"] or time.time(), why=self.obs["why"] or "interrupted", ended_t=time.time())
            self._cancel(agent, self.obs["why"])
            self.stop.update(self.obs)
            raise
        self.secs, self.obs["ended_t"] = time.time() - t0, time.time()
        deadline.check()
        if self.worker is None and live:
            self.worker = agent.worker()
        if why:
            self.stop.update(self.obs, kind="wall" if why.startswith("timeout") else "stop")
            raise Stopped(why)
        return subprocess.CompletedProcess(list(cmd), 0, json.dumps(agent.result()), "")

    def _cancel(self, agent: Agent, why: str) -> None:
        """End the worker (SIGTERM, then SIGKILL after the grace) and wait for the call's thread to hand back."""
        self.obs.update(kill_t=self.obs["kill_t"] or time.time(), why=self.obs["why"] or why)
        self.obs["alive"] = agent.stop()
