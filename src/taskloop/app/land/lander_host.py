"""What the Lander reads of the engine that is landing. LandHost holds only what the Lander's own flow reads (the tries, the lock, the
placing of the gate); every step it composes (the commit, the look for an earlier push, the rebase, the retry checks, the push, the fix
outside the lock, the after-steps, the gate, the outbound pushes) has its own host Protocol next to it, with just the members it calls.
LanderHost is only their sum: the Lander hands each step the host typed as that step's Protocol and never a wider one."""
from pathlib import Path
from typing import Protocol

from tlkernel.askspec import AskSpec
from tlkernel.beadsport import Beads
from tlkernel.checks import CheckRun
from tlkernel.gitport import Git
from tlkernel.ids import BeadId

from taskloop.app.land.fix import FixOutsideHost
from taskloop.app.land.gate import GateCheckout, GateHost, GateSteps
from taskloop.app.land.host import BeginSteps, FetchCheckout, LandLocks, MoveSteps, NetWorker, OutcomeSteps, StageCheckout, Strays
from taskloop.app.land.pr_land import PrHost
from taskloop.app.land.push import LandedHost, OutboundCheckout, OutboundHost, OutboundSteps, PushHost
from taskloop.app.land.rebase import CommitHost, LandRebaseHost, RecheckCheckpoints, RecheckHost
from taskloop.app.land.record import SyncCheckpoints, SyncHost
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class LandConfig(Protocol):
    @property
    def base(self) -> str: ...
    @property
    def gate_checks(self) -> object: ...
    @property
    def land_optimistic_tries(self) -> int: ...
    @property
    def land_mode(self) -> str: ...


class LandHost(Protocol):
    """The Lander's own flow: the guards before the commit, the tries, the optimistic gate outside the lock, and the lock."""

    pending_land_validation: str  # set while the land's retry checks still need accepted checks and review
    task_branch: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def store(self) -> Beads: ...
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
    def blocked_for(self, why: str, kind: str, *, spec: AskSpec | None = ...) -> Exception: ...
    def move_host(self, needs: list[str], why: str) -> Exception: ...


class LandSteps(OutboundSteps, OutcomeSteps, MoveSteps, GateSteps, Protocol):
    pass


class LandCheckout(FetchCheckout, StageCheckout, OutboundCheckout, GateCheckout, Protocol):
    pass


class LandCheckpoints(SyncCheckpoints, RecheckCheckpoints, Protocol):
    pass


class LanderHost(LandHost, CommitHost, LandedHost, LandRebaseHost, RecheckHost, PushHost, FixOutsideHost, SyncHost, GateHost,
                 OutboundHost, PrHost, Protocol):
    """The engine, as the land reads it: the sum of the parts above (no member of its own)."""

    # the parts that two steps type differently: the sum of what each reads
    @property
    def steps(self) -> LandSteps: ...
    @property
    def checkout(self) -> LandCheckout: ...
    @property
    def checkpoints(self) -> LandCheckpoints: ...
