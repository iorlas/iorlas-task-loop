"""The delegate of one process: the real `Route` (delegate.api), or one already chosen (the selftest)."""
from taskloop.adapters.delegate import DelegateRoute, FixedRoute
from taskloop.contracts.delegateport import Refusal, Resolved, Route, Seam


def real_route() -> Route:
    return DelegateRoute()


def fixed_route(resolved: Resolved | Refusal, process: Seam | None = None) -> Route:
    return FixedRoute(resolved, process)
