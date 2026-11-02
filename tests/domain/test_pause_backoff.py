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
    def test_engine_crash_fourth_attempt_needs_owner(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = None
        for n, wait in enumerate((60, 120, 240, 0), 1):
            rec = pauses.after_pause(rec, b, f"r{n}", 1000, "engine_crash", lambda: 0.5)
            self.assertEqual(rec.attempts, {"engine_crash": n})
            self.assertEqual(rec.permanence, "transient" if wait else "needs_owner")
            self.assertEqual(rec.retry_at, 1000 + wait if wait else 0.0)

    def test_matching_crash_site_escalates_only_across_runs(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        first = pauses.after_pause(None, b, "r1", 100, "engine_crash", lambda: 0.5, fingerprint="abc")
        self.assertEqual(first.fingerprint, "abc")
        self.assertIs(pauses.after_pause(first, b, "r1", 200, "engine_crash", lambda: 0.5, fingerprint="abc"), first)
        for fp, permanence in (("abc", "needs_owner"), ("def", "transient"), ("", "transient")):
            with self.subTest(fingerprint=fp):
                second = pauses.after_pause(first, b, "r2", 200, "engine_crash", lambda: 0.5, fingerprint=fp)
                self.assertEqual(second.permanence, permanence)
                self.assertEqual(second.attempts, {"engine_crash": 2})
                if permanence == "needs_owner":
                    self.assertEqual(second.retry_at, 0.0)

    def test_other_reasons_have_no_cap_or_fingerprint_escalation(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        for reason, policy in pauses.TABLE.items():
            if reason in ("engine_crash", "network", "pause_network"):
                continue
            rec = None
            for n in range(5):
                rec = pauses.after_pause(rec, b, f"r{n}", 100, reason, lambda: 0.5, fingerprint="abc")
                self.assertEqual(rec.permanence, policy.permanence)
                self.assertEqual(rec.retry_at, 100 + pauses.delay(policy, n, lambda: 0.5)
                                 if policy.permanence == "transient" else 0.0)

    def test_network_pauses_never_charge_attempts_or_owner_run_limits(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = pauses.after_pause(None, b, "prior", 1, "busy", lambda: 0.5)
        for n in range(20):
            for reason in ("network", "pause_network"):
                rec = pauses.after_pause(rec, b, f"{reason}-{n}", 100 + n, reason, lambda: 0.5)
                self.assertEqual(rec.attempts, {"busy": 1})
                self.assertEqual(rec.runs, 0)
                self.assertEqual(rec.permanence, "transient")
                self.assertEqual(rec.retry_at, 130 + n)

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
