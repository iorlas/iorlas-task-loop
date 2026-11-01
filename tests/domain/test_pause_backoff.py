"""A retry's backoff grows independently per reason and survives reapplying the same close."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.domain.lanes import pauses


class Backoff(unittest.TestCase):
    def test_exponential_grows_then_caps_with_injected_twenty_percent_jitter(self):
        policy = pauses.PauseRule("transient", 10, 40)
        self.assertEqual([pauses.delay(policy, n, lambda: 0.5) for n in range(5)], [10, 20, 40, 40, 40])
        for n in (0, 1, 2, 10000):
            middle = min(10 * 2 ** min(n, 10), 40)
            self.assertAlmostEqual(pauses.delay(policy, n, lambda: 0), middle * 0.8)
            self.assertAlmostEqual(pauses.delay(policy, n, lambda: 1), middle * 1.2)

    def test_reason_counts_survive_other_reasons_and_the_same_run_is_idempotent(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        first = pauses.after_pause(None, b, "r1", 100, "no_lane", lambda: 0.5)
        other = pauses.after_pause(first, b, "r2", 200, "busy", lambda: 0.5)
        again = pauses.after_pause(other, b, "r3", 300, "no_lane", lambda: 0.5)
        self.assertEqual((first.retry_at, other.retry_at, again.retry_at), (160, 230, 420))
        self.assertEqual(again.attempts, {"no_lane": 2, "busy": 1})
        self.assertEqual(pauses.after_pause(again, b, "r3", 999, "no_lane", lambda: 1), again)

    def test_predicted_lane_time_is_a_lower_bound_and_unknown_reasons_need_owner(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = pauses.after_pause(None, b, "r1", 100, "no_lane", lambda: 0, not_before=900)
        self.assertEqual(rec.retry_at, 900)
        for reason in ("engine_only_unenforced", "logged_out", "new_vendor_reason"):
            owner = pauses.after_pause(rec, b, "r2", 100, reason, lambda: 1, not_before=900)
            self.assertEqual((owner.permanence, owner.retry_at), ("needs_owner", 0))
