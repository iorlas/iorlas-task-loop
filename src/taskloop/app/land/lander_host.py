"""What the Lander reads of the engine that is landing. LandHost holds only what the Lander's own flow reads (the tries, the lock, the
placing of the gate); every step it composes (the commit, the look for an earlier push, the rebase, the retry checks, the push, the fix
outside the lock, the after-steps, the gate, the outbound pushes) has its own host Protocol next to it, with just the members it calls.
LanderHost is only their sum: the Lander hands each step the host typed as that step's Protocol and never a wider one."""
from pathlib import Path
from typing import Protocol

from taskloop.app.land.commit import CommitHost
from taskloop.app.land.fix_outside import FixOutsideHost
from taskloop.app.land.gate import GateHost, GateSteps
from taskloop.app.land.land_rebase import LandRebaseHost
from taskloop.app.land.landed import LandedHost
from taskloop.app.land.outbound import OutboundCheckout, OutboundHost
from taskloop.app.land.parts import BeginSteps, FetchCheckout, LandLocks, MoveSteps, NetWorker, OutcomeSteps, StageCheckout, Strays
from taskloop.app.land.push import PushHost
from taskloop.app.land.recheck import RecheckCheckpoints, RecheckHost
from taskloop.app.land.sync import SyncCheckpoints, SyncHost
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.ports import Git
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class LandConfig(Protocol):
    @property
    def base(self) -> str: ...
    @property
    def gate_checks(self) -> object: ...
    @property
    def land_optimistic_tries(self) -> int: ...


class LandHost(Protocol):
    """The Lander's own flow: the guards before the commit, the tries, the optimistic gate outside the lock, and the lock."""

    pending_land_validation: str  # set while the land's retry checks still need accepted checks and review
    task_branch: str

    @property
    def cfg(self) -> LandConfig: ...
    @property
    def dry(self) -> bool: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def last_run(self) -> CheckRun | None: ...
    @property
    def stores(self) -> Stores: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def steps(self) -> BeginSteps: ...
    @property
    def checkout(self) -> FetchCheckout: ...
    @property
    def newfiles(self) -> Strays: ...
    @property
    def waits(self) -> LandLocks: ...
    @property
    def worker(self) -> NetWorker: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def land_lock_path(self) -> Path: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def move_host(self, needs: list[str], why: str) -> Exception: ...


class LandSteps(BeginSteps, OutcomeSteps, MoveSteps, GateSteps, Protocol):
    pass


class LandCheckout(FetchCheckout, StageCheckout, OutboundCheckout, Protocol):
    pass


class LandCheckpoints(SyncCheckpoints, RecheckCheckpoints, Protocol):
    pass


class LanderHost(LandHost, CommitHost, LandedHost, LandRebaseHost, RecheckHost, PushHost, FixOutsideHost, SyncHost, GateHost,
                 OutboundHost, Protocol):
    """The engine, as the land reads it: the sum of the parts above (no member of its own)."""

    # the parts that two steps type differently: the sum of what each reads
    @property
    def steps(self) -> LandSteps: ...
    @property
    def checkout(self) -> LandCheckout: ...
    @property
    def checkpoints(self) -> LandCheckpoints: ...
