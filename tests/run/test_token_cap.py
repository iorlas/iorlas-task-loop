"""engine.bead_token_cap: a bead's tokens over all its runs stop the next worker call, as a budget ask with the total.
Waits runs here over a small typed host (support/narrow_hosts.py FakeWaitsHost), not an Engine."""

from typing import Any, ClassVar

import pytest
from support.narrow_hosts import FakeWaitsHost

from taskloop.adapters import deadline
from tltestkit.case import Case

# isort: split
from tlkernel.ids import RunId
from tlkernel.kinds import Kind
from tlkernel.waitenums import WaitWhat
from tlpipeline.api import Blocked, Waits
from tlpipeline.api import trace as runtrace


class TokenCap(Case):
    def waits_with(self, earlier, cap):
        """Waits over a host whose bead has one earlier run per entry of `earlier` ((in, out) tokens), and another bead's run as well."""
        host = FakeWaitsHost(bead_token_cap=cap)
        rows = [("t-1", t) for t in earlier] + [("t-9", (50_000_000, 0))]
        for n, (bead, (i, o)) in enumerate(rows):
            host.stores.traces.append(runtrace.run_trace(str(RunId.new(1.8e9 + n, bytes(10))), {
                "bead": bead, "outcome": "blocked", "stats": {"tokens_in": i, "tokens_out": o}, **self.TRACE_FIELDS}))
        return host, Waits(host, deadline)

    TRACE_FIELDS: ClassVar[dict[str, Any]] = {
        "repo_url": "r", "worktree": "w", "branch": "b", "coordinator_session": "s", "started": 1.0, "ended": 2.0, "why": "", "sha": ""}

    def test_earlier_runs_over_the_cap_stop_the_run_with_the_total(self):
        _, waits = self.waits_with([(10_000_000, 2_000_000), (5_000_000, 1_200_000)], 15_000_000)
        with pytest.raises(Blocked) as b:
            waits.budget_check()
        assert "bead used 18.2M tokens over 2 runs (cap 15M): raise engine.bead_token_cap or split the bead" in str(b.value)
        assert b.value.kind == Kind.ASK_BUDGET

    def test_under_the_cap_runs_as_before(self):
        self.waits_with([(5_000_000, 1_000_000)], 15_000_000)[1].budget_check()

    def test_no_cap_is_no_limit(self):
        self.waits_with([(500_000_000, 1_000_000)], 0)[1].budget_check()

    def test_crossing_the_cap_in_the_run_stops_before_the_next_call(self):
        host, waits = self.waits_with([(5_000_000, 0)], 7_000_000)
        waits.budget_check()
        host.stats["tokens_in"], host.stats["tokens_out"] = 1_500_000, 600_000
        with pytest.raises(Blocked) as b:
            waits.budget_check()
        assert "bead used 7.1M tokens over 2 runs (cap 7M)" in str(b.value)

    def test_a_wait_is_booked_outside_the_budget_and_ends_its_record(self):
        host, waits = self.waits_with([], 0)
        host.fake_clock.advance(600)
        waits.add(120, WaitWhat.CHECK_SLOT)
        assert host.budget.waited == 120
