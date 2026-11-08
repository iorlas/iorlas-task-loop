"""A run's lease lives inside the run's exception boundary: a failure between the claim and the launch releases it (tl-3cl.7, C14)."""

from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from run_support import RunBase
from test_route import why

from delegate.app import env
from delegate.app.run import Run
from tltestkit.procsim import real_proc


class LeaseBoundary(RunBase):
    @real_proc("delegate: a worker, git or CLI process")
    def test_a_failure_after_the_claim_releases_the_lease_and_launches_nothing(self):
        started = self.play()
        with mock.patch.object(Run, "_hooks", side_effect=OSError("hooks broke")):
            _, r = self.run_it()
        assert why(r) == "crash"
        assert "hooks broke" in r["say"]
        assert env.load_state().leases == {}  # released, not left to expire
        assert not started  # no worker was launched
