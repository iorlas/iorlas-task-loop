"""The task engine: one bead through reset, plan, (write, checks, review) per stage, gate, land, close. The Engine is the composition
root of a run: it opens the run's identity, layout and context from the edge, and hands the rest to host.py's parts."""
import shutil
import time
from pathlib import Path
from typing import Any

from taskloop.adapters import context_size, landlock, opencode
from taskloop.adapters.clock import SystemClock
from taskloop.app.checks.runner import Checker
from taskloop.app.release import reexec, seams
from taskloop.app.run import ended
from taskloop.app.run.blocked import Blocked, FixFailed
from taskloop.app.run.console import say
from taskloop.app.run.context import RunContext
from taskloop.app.run.host import RunHost
from taskloop.app.run.layout import RunLayout, finish_of, live_run, loop_id_of, loop_of, repo_of
from taskloop.app.run.stages import run_stages
from taskloop.app.run.state import carries_state
from taskloop.contracts import fence, rundocs
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.ports import Clock, Git, Spawner
from taskloop.contracts.run import RunReport
from taskloop.domain import outcome as oc
from taskloop.stores.bundle import Stores
from taskloop.stores.real import real_stores

__all__ = ["Blocked", "Engine", "FixFailed", "tool_on_path"]


def tool_on_path(name: str) -> str | None:
    return shutil.which(name)


@carries_state
class Engine(RunHost):
    def __init__(
        self,
        bead: BeadId,
        wt: str,
        cfg: EngineConfig,
        dry_run: bool = False,
        verbose: bool = True,
        store: Any = None,
        route: Any = None,
        clock: Clock | None = None,
        stores: Stores | None = None,
        fresh: bool = False,
        claim: fence.Claim | None = None,
        *,
        env: Env,
        spawner: Spawner,
        git: Git,
        who: Identity,
        mode: str = "task",
    ) -> None:
        route = route or seams.DelegateRoute(env)
        self.env = env  # the process environment, taken once at the edge (tl.py); every child is built from it
        self.spawner = spawner
        self.who = who  # the session and bd actor this run acts as, built at the edge
        self.home = who.config  # the config dir of the identity, built at the edge
        self.git = git  # the port every git call of the run goes through, pinned to the slot, built at the edge with the same env
        super().__init__(bead, wt, cfg, dry_run, verbose, store, route, fresh, claim, who)
        self.clock = clock or SystemClock()
        self.reexec = reexec.take_reexec(env)  # this run-task came from an exec into a newer install, or a fallback
        if self.reexec and self.reexec.bead != bead:
            self.reexec = None
        # a network pause continues its work and budget under a new run id; the old answer remains terminal
        pause = None if self.reexec else reexec.take_net_pause(self.home, bead)
        self.stores = stores or real_stores(self.home)
        # a run that died inside its close: its id goes on (the keys of the effects it applied are under it)
        ck = None if dry_run or self.reexec or pause else self.checkpoints.read()
        self.dead = ck if ended.unfinished(ck) else None
        # exec and an unfinished close retain their run id; a completed network pause retains only its counters
        dead_run = self.dead.ended.run if self.dead and self.dead.ended else None
        taken = (self.reexec.run if self.reexec else None) or (live_run(self.home, pause.run) if pause else None) or dead_run
        layout = RunLayout.open(bead, wt, taken, self.home, repo_of(self.git, wt), self.clock.now(),
                                loop=loop_of(self.env, self.git, wt), loop_id=loop_id_of(self.env),
                                mode=mode, owner=who.actor, session=who.session)
        self.log_path, self.err_path, self.run_dir, self.live_dir = layout.log_path, layout.err_path, layout.run_dir, layout.live_dir
        self.run_id = layout.run  # the run's id: TL_RUN_ID in its checks, run_id in its rows
        self.task_dir, self.brief_file, self.evidence_dir = layout.task_dir, layout.brief_file, layout.evidence_dir
        self.exec_fn = None
        self.newer_fn = None
        self.argv = None
        self.moved = False
        self.os_lock = landlock.os_lock
        stem = self.run_id
        self.ctx = RunContext.open(bead, cfg, Path(wt), stem, self.run_dir, self.home, self.stores, store, route, self.clock, self.sessions,
                                   self.stats, opencode.opencode_id, lambda p: context_size.context_tokens(p, self.env), say,
                                   verbose, dry_run, self.now, self.step_guard, self.on_step)
        c = self.ctx
        self.log, self.steps, self.budget, self.calls, self.checklog = c.log, c.steps, c.budget, c.calls, c.checklog
        self.checker = Checker(self, lambda secs: self.halt_point(wait=secs))
        self.delegation.route(quiet=True)
        if self.reexec:
            self.reload.restore_run(rundocs.reexec(self.home, self.run_id))
        elif pause:
            self.reload.restore_run(rundocs.pause(self.home, pause.run))
            self.reload.carry_done_memo(self.home.run_dir(pause.run))
            self.log.note(f"back from the network pause of {pause.run}: continuing as run {stem}")

    @property
    def intake_per_day(self) -> int:
        return self.cfg.intake_per_day

    def on_path(self, name: str) -> str | None:
        return tool_on_path(name)

    def run(self, *, stage: str | None = None, continuous: bool = True) -> int:
        return run_stages(self, stage, continuous=continuous and stage is None)

    def result(self) -> RunReport:
        """The run's outcome for the loop: landed (closed, done too), parked (blocked for the owner: an ask, or one
        still open), paused (the machine's trouble: lanes, login, network; the bead stays open), failed."""
        finish = finish_of(self.home, self.run_id)
        kind = Kind(finish.kind) if finish else self.kind
        out = finish.result if finish else oc.POLICY[kind].loop
        paused = out is Result.PAUSED or kind is Kind.ENGINE_CRASH
        return RunReport(outcome=out, bead=self.bead, why=(finish.why if finish else self.why)[:500],
                         run=self.run_id, log=str(self.log_path),
                         minutes=round(((finish.ended if finish else time.time()) - self.t0) / 60, 1), rounds=self.stats["rounds"],
                         tests_added=self.stats["tests_added"], asked=self.asked, retry_after=self.retry_after if paused else 0.0,
                         cost=round(self.cost, 2), kind=kind.value, fingerprint=self.fp, storm=self.storm,
                         role=self.pause_role if paused else "", lane=self.pause_lane if paused else "")
