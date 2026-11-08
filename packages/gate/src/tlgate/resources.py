"""Resources: the scarce tools a check may need (`needs: ["editor"]`, declared in engine.resources with a machine-wide `limit`).

A check holds one lease per resource it needs while it runs. A lease is one of `limit` units of the machine's lease table
(~/.config/task-loop/leases, any_lease), so the limit holds across slots, loops and manual runs (`python3 -m any_lease run
--root <table> editor N label -- cmd`), and a dead holder frees its unit by itself (a flock). The holder record is the label
`bead:check` plus its track; `tl status` and the dashboard read it. The wait is recorded: in the wait log (WaitWhat.RESOURCE, with
the check, its track and the holders; outside the run's budget) and per check (`CheckResult.waited`, `CheckEnd.waited`).
The check's command gets ANY_LEASE_HELD and ANY_LEASE_ROOT, so a manual-run wrapper inside it does not take a second unit.

Which resources this host has is ~/.config/task-loop/host.json (HostResources); a check that needs one the host lacks is not run here
(`lacking`): the executor defers it."""
import contextlib
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Protocol

from any_lease import LeaseCancelledError, Waiting
from tlkernel.checks import Check
from tlkernel.config import EngineConfig
from tlkernel.waitenums import WaitWhat

from tlgate.domain import affinity
from tlgate.ports import GateStores

POLL_S = 0.5  # how often a waiting check looks for a free lease


class ResourceWaits(Protocol):
    def start(self, what: WaitWhat, holder: str = ..., until: float | None = ..., track: str = ..., check: str = ...) -> str: ...
    def add(self, secs: float, what: WaitWhat, wid: str | None = ..., track: str = ..., check: str = ...) -> None: ...


class ResourceHost(Protocol):
    """What the leases read of the engine (the CheckHost has it all)."""

    @property
    def bead(self) -> str: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def stores(self) -> GateStores: ...
    @property
    def waits(self) -> ResourceWaits: ...

    def warn(self, text: str) -> None: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...


class LeaseCancelled(Exception):
    """The track of a check that was queuing for a lease went red-elsewhere: it stops waiting (nothing is held)."""


@dataclass
class Lease:
    waited: float = 0.0  # seconds spent queuing for the leases of one check
    env: dict[str, str] = field(default_factory=dict[str, str])  # what the check's command is told of the leases it holds


class Resources:
    def __init__(self, host: ResourceHost) -> None:
        self.host = host
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
    def hold(self, c: Check, cancel: threading.Event | None = None) -> Generator[Lease]:
        """Hold a lease on each resource the check needs (in name order, so two checks never wait on each other), for the block, which
        frees them however it ends. `cancel` set while it queues: LeaseCancelled, holding none."""
        lease = Lease()
        if not c.needs:
            yield lease
            return
        with contextlib.ExitStack() as stack:
            for name in sorted(c.needs):
                lease.waited += self._take(stack, c, name, cancel)
            lease.env = {"ANY_LEASE_HELD": ":".join(sorted(c.needs)), "ANY_LEASE_ROOT": str(self.host.stores.leases.root)}
            yield lease

    def _declare(self, name: str, limit: int) -> None:
        """The profile's limit is the one declared number; the table keeps it (`<name>.limit`). A changed profile limit replaces the
        old one while nothing holds the resource; while it is held, the ValueError (naming both numbers) stops the check."""
        leases = self.host.stores.leases
        try:
            leases.declare(name, limit)
        except ValueError:
            if leases.holders(name):
                raise
            (leases.root / f"{name}.limit").unlink(missing_ok=True)
            leases.declare(name, limit)

    def _take(self, stack: contextlib.ExitStack, c: Check, name: str, cancel: threading.Event | None) -> float:
        """Win one of the resource's `limit` units (waiting for one); -> the seconds waited."""
        host, limit = self.host, self.host.cfg.resources[name].limit
        wid: list[str] = []
        self._declare(name, limit)

        def waiting(w: Waiting) -> None:
            if not wid:
                who = ", ".join((o.holder.label or "?") if o.holder else "?" for o in w.occupants)
                wid.append(host.waits.start(WaitWhat.RESOURCE, who, track=c.track, check=c.id))
                host.warn(f"waiting for the {name} resource ({limit} at a time on this machine; held by {who})")
            host.halt_point()

        try:
            held = host.stores.leases.acquire(name, limit, cancel=cancel, label=f"{host.bead}:{c.id}", on_wait=waiting, poll=POLL_S,
                                              meta={"bead": host.bead, "check": c.id, "track": c.track})
        except LeaseCancelledError as e:
            raise LeaseCancelled(name) from e
        stack.callback(held.release)
        if wid:
            host.waits.add(held.waited, WaitWhat.RESOURCE, wid[0], track=c.track, check=c.id)
        return held.waited
