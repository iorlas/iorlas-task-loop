"""`ApiAgent`: the `Agent` of `delegate.api`. `api.run` on a thread of its own; the Handle and `api.cancel` stay in here."""
import threading
from typing import Self

from delegate import api
from taskloop.adapters import procs


def running_for(task: str) -> list[str]:
    """The runs delegate says still go for this task (the ids): a worker that outlived its engine. None when there is no task or delegate
    cannot say."""
    if not task:
        return []
    try:
        return [a.run_id for a in api.agents() if a.task == task]
    except (Exception, SystemExit):
        return []


class ApiAgent:
    def __init__(self, request: api.RunRequest, grace: float = procs.STOP_GRACE_S) -> None:
        self.request, self.grace = request, grace
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
