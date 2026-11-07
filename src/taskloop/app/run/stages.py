"""Bind standalone steps to the stage implementations at the application root."""
from functools import partial

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
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import real_log


class RoundStages:
    def __init__(self, host: RunHost) -> None:
        self.host = host

    def round_step(self, step: Step, ck: Checkpoint | None) -> Step:
        return round_step(self.host, step, ck)


def run_stages(runner: RunHost, requested: str | None, *, continuous: bool) -> int:
    once = RunOnce(runner)
    standalone = Standalone(runner, rounds=RoundStages(runner), once=lambda: once, lease=once.lease,
                            closing=ClosingBeads(runner.who, runner.store, guard_for(runner.who, runner.store, runner.git, runner.wt)),
                            has_land=lambda: has_land(runner.who, runner.bead), repo_of=repo_of,
                            stage_run=partial(stage_run, stores_factory=real_stores,
                                              log_factory=real_log))
    return standalone.run_stages(requested, continuous=continuous)
