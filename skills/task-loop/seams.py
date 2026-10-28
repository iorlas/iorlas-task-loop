"""The defaults of the engine's injectable seams: bd (`store`), the delegate (`route`). Tests pass fakes (tests/support/fakes.py).

`store` answers `show(bead)`, `comments(bead)` and `bd(*argv)` (a process-like result); `route` answers `resolve(delegate_cfg)`
(delegate_link.Resolved or Refusal) and `runner(log_path, idle, wall)` (the process seam of delegate_link.call). Both defaults look the
real function up at call time, so they follow whatever `tl` and `delegate_link` are at that moment."""
import delegate_link as dl
import tl


class TlStore:
    def show(self, bead, cwd=None):
        return tl.show(bead, cwd=cwd) if cwd else tl.show(bead)

    def comments(self, bead, cwd=None):
        return tl.comments(bead, cwd=cwd) if cwd else tl.comments(bead)

    def bd(self, *args, cwd=None):
        return tl.bd(*args, cwd=cwd) if cwd else tl.bd(*args)


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
