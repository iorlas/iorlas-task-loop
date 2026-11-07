"""Bind the run body, lifecycle and lease at the application root."""
from collections.abc import Callable
from typing import Any

from tlkernel.envvars import EnvVar

from taskloop.app.land.closing import LandHistory
from taskloop.app.pipeline.lifecycle import Lifecycle
from taskloop.app.pipeline.run import RunBody
from taskloop.app.release.closing import ReexecBook
from taskloop.app.slots.lease import Lease


class RunOnce:
    def __init__(self, host: Any) -> None:
        self.host = host
        body = RunBody(host, LandHistory(host.git), self.beat)
        self.lifecycle = Lifecycle(host, body=body.run, lease=self.lease, reexecs=ReexecBook(host.home))

    def lease(self, on_beat: Callable[[], None], on_death: Callable[[BaseException], None]) -> Lease:
        host = self.host
        return Lease(host.store, host.bead, host.env.bead(EnvVar.TASK_LOOP_SLOT_BEAD), on_beat=on_beat, on_death=on_death)

    def go(self) -> int:
        return self.lifecycle.go()

    def beat(self) -> None:
        self.lifecycle.beat()

    def beat_died(self, err: BaseException) -> None:
        self.lifecycle.beat_died(err)

