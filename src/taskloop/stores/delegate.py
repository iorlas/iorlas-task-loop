"""The delegate of one process: the real `Route` (delegate.api), or one already chosen (the selftest)."""
from taskloop.adapters.delegate import DelegateRoute, FixedRoute
from taskloop.contracts.delegateport import Probe, Refusal, Resolved, Route, Seam


def real_route() -> Route:
    return DelegateRoute()


def fixed_route(resolved: Resolved | Refusal, process: Seam | None = None) -> Route:
    return FixedRoute(resolved, process)


def route_name() -> str | None:
    """The route the engine's calls go through (the delegate library); None when delegate is refused."""
    found = real_route().resolve()
    return found.route if isinstance(found, Resolved) else None


def make_probe(hosts: tuple[str, ...]) -> Probe | None:
    """delegate's network probe over `hosts`; None when delegate is refused."""
    return real_route().probe(hosts) if route_name() else None
