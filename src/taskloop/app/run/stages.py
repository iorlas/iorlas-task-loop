"""Bind standalone steps to the stage implementations at the application root."""
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step

from taskloop.app.pipeline.stage_run import stage_run
from taskloop.app.pipeline.standalone import Standalone
from taskloop.app.run.host import RunHost
from taskloop.app.run.layout import repo_of
from taskloop.app.run.run_once import RunOnce
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire.closeguard import guard_for, has_land
from taskloop.app.write.rounds import round_step


class RoundStages:
    def __init__(self, host: RunHost) -> None:
        self.host = host

    def round_step(self, step: Step, ck: Checkpoint | None) -> Step:
        return round_step(self.host, step, ck)


def run_stages(e: RunHost, requested: str | None, *, continuous: bool) -> int:
    once = RunOnce(e)
    standalone = Standalone(e, e, e, e, e, rounds=RoundStages(e), once=lambda: once, lease=once.lease,
                            closing=ClosingBeads(e.who, e.store, guard_for(e.who, e.store, e.git, e.wt)),
                            has_land=lambda: has_land(e.who, e.bead), repo_of=repo_of, stage_run=stage_run)
    return standalone.run_stages(requested, continuous=continuous)
