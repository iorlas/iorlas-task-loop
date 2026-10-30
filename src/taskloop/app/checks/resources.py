"""Resources: the scarce tools a check may need (`needs: ["unity"]`, declared in engine.resources with a machine-wide `limit`).

A check holds one lease per resource it needs while it runs. A lease is one of `limit` named locks of the machine's lock table
(~/.config/task-loop/locks), so the limit holds across slots and loops and a dead holder frees its lease by itself. The wait is
recorded: in the wait log (WaitWhat.RESOURCE, outside the run's budget) and per check (`CheckResult.waited`, `CheckEnd.waited`).

Which resources this host has is ~/.config/task-loop/host.json (HostResources); a check that needs one the host lacks is not run here
(`lacking`): the executor defers it."""
import contextlib
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Protocol

from taskloop.contracts.checks import Check
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import LockWhat, WaitWhat
from taskloop.contracts.locks import LockTimeout
from taskloop.domain.checks import affinity
from taskloop.stores.bundle import Stores

POLL_S = 0.5  # how often a waiting check looks for a free lease


class ResourceWaits(Protocol):
    def start(self, what: WaitWhat, holder: str = ..., until: float | None = ...) -> str: ...
    def add(self, secs: float, what: WaitWhat, wid: str | None = ...) -> None: ...


class ResourceHost(Protocol):
    """What the leases read of the engine (the CheckHost has it all)."""

    @property
    def bead(self) -> str: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def stores(self) -> Stores: ...
    @property
    def waits(self) -> ResourceWaits: ...

    def warn(self, text: str) -> None: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...


@dataclass
class Lease:
    waited: float = 0.0  # seconds spent queuing for the leases of one check


class Resources:
    def __init__(self, host: ResourceHost, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.sleep = host, sleep
        self._have: set[str] | None = None

    def have(self) -> set[str]:
        """The resources this host has: host.json's list; no file: every resource the repo declares."""
        if self._have is None:
            self._have = affinity.have(self.host.cfg, self.host.stores.host.need())
        return self._have

    def lacking(self, c: Check) -> list[str]:
        """The resources the check needs and this host does not have."""
        return [n for n in c.needs if n not in self.have()]

    @contextlib.contextmanager
    def hold(self, c: Check) -> Generator[Lease]:
        """Hold a lease on each resource the check needs (in name order, so two checks never wait on each other), for the block."""
        lease = Lease()
        if not c.needs:
            yield lease
            return
        with contextlib.ExitStack() as stack:
            for name in sorted(c.needs):
                lease.waited += self._take(stack, name, f"{self.host.bead}:{c.id}")
            yield lease

    def _take(self, stack: contextlib.ExitStack, name: str, who: str) -> float:
        """Win one of the resource's `limit` leases (waiting for one); -> the seconds waited."""
        locks, limit = self.host.stores.locks, self.host.cfg.resources[name].limit
        started, wid = time.time(), None
        while True:
            for i in range(limit):
                try:
                    stack.enter_context(locks.hold(LockWhat.RESOURCE, f"{name}-{i}", who, timeout=0))
                except LockTimeout:
                    continue
                waited = time.time() - started if wid is not None else 0.0
                if wid is not None:
                    self.host.waits.add(waited, WaitWhat.RESOURCE, wid)
                return waited
            if wid is None:
                wid = self.host.waits.start(WaitWhat.RESOURCE, name)
                self.host.warn(f"waiting for the {name} resource ({limit} at a time on this machine)")
            self.host.halt_point()
            self.sleep(POLL_S)
