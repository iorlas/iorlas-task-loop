"""A retry's backoff grows independently per reason and survives reapplying the same close."""


import pytest

from tlkernel import lanepauses as pauses
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.pausereasons import Reason, Unknown, parse
from tltestkit.case import Case


class Backoff(Case):
    def test_engine_crash_fourth_attempt_needs_owner(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = None
        for n, wait in enumerate((60, 120, 240, 0), 1):
            rec = pauses.after_pause(rec, b, f"r{n}", 1000, "engine_crash", lambda: 0.5)
            assert rec.attempts == {"engine:engine_crash": n}
            assert rec.permanence == ("transient" if wait else "needs_owner")
            assert rec.retry_at == (1000 + wait if wait else 0.0)

    def test_matching_crash_site_escalates_only_across_runs(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        first = pauses.after_pause(None, b, "r1", 100, "engine_crash", lambda: 0.5, fingerprint="abc")
        assert first.fingerprint == "abc"
        assert pauses.after_pause(first, b, "r1", 200, "engine_crash", lambda: 0.5, fingerprint="abc") is first
        for fp, permanence in (("abc", "needs_owner"), ("def", "transient"), ("", "transient")):
            with self.subTest(fingerprint=fp):
                second = pauses.after_pause(first, b, "r2", 200, "engine_crash", lambda: 0.5, fingerprint=fp)
                assert second.permanence == permanence
                assert second.attempts == {"engine:engine_crash": 2}
                if permanence == "needs_owner":
                    assert second.retry_at == 0.0

    def test_every_non_network_transient_reason_stops_after_its_cap(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        for (producer, reason), policy in pauses.TABLE.items():
            if policy.permanence != "transient" or not policy.max_attempts:
                continue
            rec = None
            with self.subTest(producer=producer, reason=reason):
                for n in range(policy.max_attempts + 2):
                    rec = pauses.after_pause(rec, b, f"r{n}", 100, reason, lambda: 0.5, producer=producer)
                    transient = n < policy.max_attempts
                    assert rec.permanence == ("transient" if transient else "needs_owner")
                    assert rec.retry_at == (100 + pauses.delay(policy, n, lambda: 0.5) if transient else 0.0)

    def test_network_pauses_never_charge_attempts_or_owner_run_limits(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = pauses.after_pause(None, b, "prior", 1, "busy", lambda: 0.5, permanence="transient")
        for n in range(20):
            for reason in ("network", "pause_network"):
                rec = pauses.after_pause(rec, b, f"{reason}-{n}", 100 + n, reason, lambda: 0.5, permanence="transient")
                assert rec.attempts == {"delegate:busy": 1}
                assert rec.runs == 0
                assert rec.permanence == "transient"
                assert rec.retry_at == 130 + n

    def test_exponential_grows_then_caps_with_injected_twenty_percent_jitter(self):
        policy = pauses.PauseRule("transient", 10, 40)
        assert [pauses.delay(policy, n, lambda: 0.5) for n in range(5)] == [10, 20, 40, 40, 40]
        for n in (0, 1, 2, 10000):
            middle = min(10 * 2 ** min(n, 10), 40)
            assert pauses.delay(policy, n, lambda: 0) == pytest.approx(middle * 0.8, abs=5e-08)
            assert pauses.delay(policy, n, lambda: 1) == pytest.approx(middle * 1.2, abs=5e-08)

    def test_reason_counts_survive_other_reasons_and_the_same_run_is_idempotent(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        first = pauses.after_pause(None, b, "r1", 100, "rate_limited", lambda: 0.5, permanence="transient")
        other = pauses.after_pause(first, b, "r2", 200, "busy", lambda: 0.5, permanence="transient")
        again = pauses.after_pause(other, b, "r3", 300, "rate_limited", lambda: 0.5, permanence="transient")
        assert (first.retry_at, other.retry_at, again.retry_at) == (160, 230, 420)
        assert again.attempts == {"delegate:rate_limited": 2, "delegate:busy": 1}
        assert pauses.after_pause(again, b, "r3", 999, "rate_limited", lambda: 1, permanence="transient") == again

    def test_predicted_lane_time_is_a_lower_bound_and_unknown_reasons_need_owner(self):
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = pauses.after_pause(None, b, "r1", 100, "rate_limited", lambda: 0, not_before=900, permanence="transient")
        assert rec.retry_at == 900
        for reason in ("engine_only_unenforced", "logged_out", "new_vendor_reason", "no_account", "crash"):
            owner = pauses.after_pause(rec, b, "r2", 100, reason, lambda: 1, not_before=900)
            assert (owner.permanence, owner.retry_at) == ("needs_owner", 0)

    def test_unknown_preserves_raw_value_and_cannot_borrow_another_producers_policy(self):
        assert parse("future_reason") == Unknown("future_reason")
        assert parse("busy") == Reason.BUSY
        assert pauses.rule(Unknown("busy")).permanence == "needs_owner"
        assert pauses.rule("engine_crash", "delegate").permanence == "needs_owner"
        b = Bead(id=BeadId("t-1"), title="work", status="open")
        rec = pauses.after_pause(None, b, "r1", 100, "busy", lambda: 0.5, producer="engine")
        rec = pauses.after_pause(rec, b, "r2", 100, "busy", lambda: 0.5, producer="delegate", permanence="transient")
        assert rec.attempts == {"engine:busy": 1, "delegate:busy": 1}
        assert rec.permanence == "transient"
