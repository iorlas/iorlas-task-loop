"""The defaults of the engine's injectable seam `route`: the delegate. Tests pass fakes (tests/support/fakes.py).

`route` answers `resolve(delegate_cfg)` (adapters.delegate.Resolved or Refusal) and `runner(log_path, wall, live, on_worker)` (the
process seam of `adapters.delegate.call`); the default looks
the real function up at call time. The bd seam is `store` (taskloop.contracts.ports.Beads), made by `beadtools.bd_store()`."""
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import delegate as dg
from taskloop.adapters import ident
from taskloop.adapters.runner import Seam, StreamRunner
from taskloop.app.release import pins
from taskloop.contracts.delegate import WorkerStarted
from taskloop.contracts.env import Env


def resolve_delegate(env: Env, configured: str = "") -> dg.Resolved | dg.Refusal:
    """The delegate install for the next call: a configured path, then the pin, then the installed one."""
    return dg.resolve(configured, pins.pinned_dir("delegate", env), dg.installed_dir(ident.claude_dir(env)))


class DelegateRoute:
    def __init__(self, env: Env) -> None:
        self.env = env

    def resolve(self, configured: str = "") -> dg.Resolved | dg.Refusal:
        return resolve_delegate(self.env, configured)

    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam:
        return StreamRunner(log_path, wall, live, on_worker)


class FixedRoute:
    """A delegate that is already chosen: `resolve` answers `resolved`, `runner` hands out `runner` (the selftest and the tests)."""

    def __init__(self, resolved: dg.Resolved | dg.Refusal, runner: Seam | None = None) -> None:
        self.resolved, self.process = resolved, runner

    def resolve(self, configured: str = "") -> dg.Resolved | dg.Refusal:
        return self.resolved

    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam | None:
        return self.process
