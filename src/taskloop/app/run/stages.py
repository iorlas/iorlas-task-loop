"""Bind standalone steps to the stage implementations at the application root."""
from functools import partial

from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.runlayout import repo_of
from tlpipeline.api import Standalone, stage_run
from tlwork.api import round_step

from taskloop.adapters import beadtools
from taskloop.app.run.host import RunHost
from taskloop.app.run.run_once import RunOnce
from taskloop.app.track.closeguard import guard_for, has_land
from taskloop.app.track.closing import ClosingBeads
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import real_log


class RoundStages:
    def __init__(self, host: RunHost) -> None:
        self.host = host

    def round_step(self, step: Step, ck: Checkpoint | None) -> Step:
        return round_step(self.host, step, ck)


def run_stages(e: RunHost, requested: str | None, *, continuous: bool) -> int:
    once = RunOnce(e)
    standalone = Standalone(e, e, e, e, e, rounds=RoundStages(e), once=lambda: once, lease=once.lease,
                            closing=ClosingBeads(e.who, e.store, guard_for(e.who, e.store, e.git, e.wt,
                                                                        base_of=lambda repo, git: e.cfg.base)),
                            has_land=lambda: has_land(e.who, e.bead), repo_of=repo_of, peek_bead=beadtools.peek,
                            stage_run=partial(stage_run, stores_factory=real_stores, log_factory=real_log))
    return standalone.run_stages(requested, continuous=continuous)
