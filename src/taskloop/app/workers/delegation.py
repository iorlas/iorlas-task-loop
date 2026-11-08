"""The delegate library the next call goes through."""
from typing import Protocol

from tlkernel.delegateport import Probe, Refusal, Resolved
from tlkernel.wire import Open


class RouteLog(Protocol):
    def note(self, text: str) -> object: ...


class DelegationRoute(Protocol):
    def resolve(self) -> Resolved | Refusal: ...
    def probe(self) -> Probe: ...


class DelegationHost(Protocol):
    @property
    def router(self) -> DelegationRoute: ...
    resolved: Resolved | None
    refusal: Refusal | None
    route: str
    contract: Open | None
    probe: Probe | None

    @property
    def log(self) -> RouteLog: ...


class Delegation:
    def __init__(self, host: DelegationHost) -> None:
        self.e = host

    def route(self, quiet: bool = False) -> str:
        """The delegate for the next call (tl-6ax): resolved again each call. A refused one keeps the
        one in use (noted); with none in use the run says why."""
        e = self.e
        new = e.router.resolve()
        if isinstance(new, Refusal):
            if e.resolved is None:
                e.refusal = new
            elif not quiet:
                e.log.note(f"delegate not switched: {new.kind} {new.detail}; keeping {e.route}")
            return e.route
        if e.resolved is not None and new.route != e.resolved.route and not quiet:
            e.log.note(f"delegate switched: {e.route} -> {new.route}")
        e.resolved, e.route, e.contract, e.refusal = new, new.route, new.contract, None
        if not quiet:
            e.log.note(f"delegate call via {e.route}")
        return e.route

    def net_probe(self) -> Probe:
        """The network probe: a test's, else delegate's."""
        return self.e.probe or self.e.router.probe()
