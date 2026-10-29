"""The defaults of the engine's injectable seam `route`: the delegate. Tests pass fakes (tests/support/fakes.py).

`route` answers `resolve(delegate_cfg)` (adapters.delegate.Resolved or Refusal) and `runner(log_path, idle, wall, live, on_worker)` (the
process seam of `adapters.delegate.call`: `idle` is the silence limits (warn, stop, cap, on_warn) of a write, or None); the default looks
the real function up at call time. The bd seam is `store` (taskloop.contracts.ports.Beads), made by `beadtools.bd_store()`."""
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from taskloop.adapters import delegate as dg
from taskloop.adapters import ident
from taskloop.adapters.runner import Seam, Silence, StreamRunner
from taskloop.app.release import pins
from taskloop.contracts.delegate import WorkerStarted


def resolve_delegate(configured: str = "") -> dg.Resolved | dg.Refusal:
    """The delegate install for the next call: a configured path, then the pin, then the installed one."""
    return dg.resolve(configured, pins.pinned_dir("delegate"), dg.installed_dir(ident.claude_dir()))


class DelegateRoute:
    def resolve(self, configured: str = "") -> dg.Resolved | dg.Refusal:
        return resolve_delegate(configured)

    def runner(self, log_path: str | Path, idle: Sequence[Any] | None = None, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam:
        silence = Silence(idle[0], idle[1], idle[2], idle[3]) if idle else None
        return StreamRunner(log_path, silence, wall, live, on_worker)


class FixedRoute:
    """A delegate that is already chosen: `resolve` answers `resolved`, `runner` hands out `runner` (the selftest and the tests)."""

    def __init__(self, resolved: dg.Resolved | dg.Refusal, runner: Seam | None = None) -> None:
        self.resolved, self.process = resolved, runner

    def resolve(self, configured: str = "") -> dg.Resolved | dg.Refusal:
        return self.resolved

    def runner(self, log_path: str | Path, idle: Sequence[Any] | None = None, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam | None:
        return self.process
