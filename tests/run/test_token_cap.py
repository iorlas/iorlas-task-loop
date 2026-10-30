"""engine.bead_token_cap: a bead's tokens over all its runs stop the next worker call, as a budget ask with the total.
Waits runs here over a small typed host (support/narrow_hosts.py FakeWaitsHost), not an Engine."""
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow_hosts import FakeWaitsHost

# isort: split
from taskloop.app.run import trace as runtrace
from taskloop.app.run.blocked import Blocked
from taskloop.app.run.waits import Waits
from taskloop.contracts.enums import WaitWhat
from taskloop.domain import outcome as oc


class TokenCap(unittest.TestCase):
    def waits_with(self, earlier, cap):
        """Waits over a host whose bead has one earlier run per entry of `earlier` ((in, out) tokens), and another bead's run as well."""
        host = FakeWaitsHost(bead_token_cap=cap)
        rows = [("t-1", t) for t in earlier] + [("t-9", (50_000_000, 0))]
        for n, (bead, (i, o)) in enumerate(rows):
            host.stores.traces.append(runtrace.run_trace(f"{bead}-20261029-10000{n}", {
                "bead": bead, "outcome": "blocked", "stats": {"tokens_in": i, "tokens_out": o}, **self.TRACE_FIELDS}))
        return host, Waits(host)

    TRACE_FIELDS: ClassVar[dict[str, Any]] = {
        "repo_url": "r", "worktree": "w", "branch": "b", "coordinator_session": "s", "started": 1.0, "ended": 2.0, "why": "", "sha": ""}

    def test_earlier_runs_over_the_cap_stop_the_run_with_the_total(self):
        _, waits = self.waits_with([(10_000_000, 2_000_000), (5_000_000, 1_200_000)], 15_000_000)
        with self.assertRaises(Blocked) as b:
            waits.budget_check()
        self.assertIn("bead used 18.2M tokens over 2 runs (cap 15M): raise engine.bead_token_cap or split the bead", str(b.exception))
        self.assertEqual(b.exception.kind, oc.Kind.ASK_BUDGET)

    def test_under_the_cap_runs_as_before(self):
        self.waits_with([(5_000_000, 1_000_000)], 15_000_000)[1].budget_check()

    def test_no_cap_is_no_limit(self):
        self.waits_with([(500_000_000, 1_000_000)], 0)[1].budget_check()

    def test_crossing_the_cap_in_the_run_stops_before_the_next_call(self):
        host, waits = self.waits_with([(5_000_000, 0)], 7_000_000)
        waits.budget_check()
        host.stats["tokens_in"], host.stats["tokens_out"] = 1_500_000, 600_000
        with self.assertRaises(Blocked) as b:
            waits.budget_check()
        self.assertIn("bead used 7.1M tokens over 2 runs (cap 7M)", str(b.exception))

    def test_a_wait_is_booked_outside_the_budget_and_ends_its_record(self):
        host, waits = self.waits_with([], 0)
        host.fake_clock.advance(600)
        waits.add(120, WaitWhat.UNITY_SLOT)
        self.assertEqual(host.budget.waited, 120)


if __name__ == "__main__":
    unittest.main()
