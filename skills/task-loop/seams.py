"""The defaults of the engine's injectable seam `route`: the delegate. Tests pass fakes (tests/support/fakes.py).

`route` answers `resolve(delegate_cfg)` (delegate_link.Resolved or Refusal) and `runner(log_path, idle, wall)` (the process seam of
delegate_link.call); the default looks the real function up at call time. The bd seam is `store` (taskloop.contracts.ports.Beads),
made by `tl.bd_store()`."""
import delegate_link as dl


class DelegateRoute:
    def resolve(self, configured=""):
        return dl.resolve(configured)

    def runner(self, log_path, idle=None, wall=None):
        return dl.ProcRunner(log_path, idle, wall)


class FixedRoute:
    """A delegate that is already chosen: `resolve` answers `resolved`, `runner` hands out `runner` (the selftest and the tests)."""

    def __init__(self, resolved, runner=None):
        self.resolved, self.process = resolved, runner

    def resolve(self, configured=""):
        return self.resolved

    def runner(self, log_path, idle=None, wall=None):
        return self.process
