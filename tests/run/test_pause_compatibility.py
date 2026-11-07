"""Transient retry scheduling must not change existing owner, ask or infrastructure closes."""

import sys
from pathlib import Path
from unittest import mock

import pytest
from support.parkmock import through_change

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.asks import parks
from taskloop.app.asks.closing import ClosingAsks
from taskloop.app.pipeline.closing import Closer
from taskloop.domain.beads import park
from taskloop.domain.beads.park import text_hash
from taskloop.domain.lanes import pauses
from tlkernel import runoutcome as oc
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import ASKS, FAULTS, Kind
from tlkernel.parks import Park


class PauseCompatibility(Case):
    def setup_method(self):
        self.bead = Bead(id=BeadId("t-1"), title="work", status="open")
        self.cfg = mock.Mock()

    def test_machine_pauses_keep_owner_parks_without_an_ask(self):
        for reason in (
            "no_lane",
            "logged_out",
            "secrets",
            "credit_exhausted",
            "setup",
            "contract_violation",
            "engine_only_unenforced",
        ):
            with self.subTest(reason=reason), mock.patch.object(parks, "ParkStore") as store:
                through_change(store)
                host = mock.Mock(
                    dry=False, home=self.cfg, bead=self.bead.id, run_id="r1", pause_reason=reason,
                    pause_producer="delegate", pause_permanence="needs_owner", retry_after=0.0, asked=False
                )
                store.return_value.get.return_value = None
                host.clock.now.return_value = 100
                for n in range(4):
                    host.run_id = f"r{n}"
                    with mock.patch("taskloop.app.pipeline.closing.beadtools.peek", return_value=self.bead):
                        Closer(host, mock.Mock(), ClosingAsks(host.home), ClosingAsks(host.home)).pause(oc.make(Kind.PAUSE_LANE, "paused"))
                    assert (host.retry_after, host.asked, host.pause_reason) == (0, False, reason)
                    host.ask_flow.raise_ask.assert_not_called()
                    rec = store.return_value.put.call_args.args[0]
                    assert (rec.reason, rec.permanence, rec.retry_at) == (reason, "needs_owner", 0)
                    store.return_value.get.return_value = rec

    def test_owner_pauses_without_retry_caps_ask_unless_the_machine_needs_repair(self):
        for reason, producer in (("stage_refused", "engine"), ("crash", "delegate"), ("new_vendor_reason", "delegate")):
            with self.subTest(reason=reason), mock.patch.object(parks, "ParkStore") as store:
                through_change(store)
                host = mock.Mock(
                    dry=False, home=self.cfg, bead=self.bead.id, run_id="r1", pause_reason=reason,
                    pause_producer=producer, pause_permanence="needs_owner", retry_after=0.0, asked=False
                )
                store.return_value.get.return_value = None
                host.clock.now.return_value = 100
                host.ask_flow.raise_ask.return_value = True
                assert pauses.rule(reason, producer).max_attempts == 0
                with mock.patch("taskloop.app.pipeline.closing.beadtools.peek", return_value=self.bead):
                    Closer(host, mock.Mock(), ClosingAsks(host.home), ClosingAsks(host.home)).pause(oc.make(Kind.PAUSE_LANE, "paused"))
                assert (host.retry_after, host.asked) == (0, True)
                host.ask_flow.raise_ask.assert_called_once()
                rec = store.return_value.put.call_args.args[0]
                assert (rec.reason, rec.permanence, rec.retry_at) == (reason, "needs_owner", 0)

    def test_every_capped_policy_is_charged_by_the_pause_path(self):
        policies = dict(pauses.TABLE)
        for reason in pauses.BACKOFF:
            if pauses.BACKOFF[reason] is None:
                continue
            policies[("delegate", reason)] = pauses.rule(reason, "delegate", "transient")
        for (producer, reason), policy in policies.items():
            if not policy.max_attempts:
                continue
            with self.subTest(producer=producer, reason=reason), mock.patch.object(parks, "ParkStore") as store:
                through_change(store)
                store.return_value.get.return_value = None
                for n in range(policy.max_attempts + 1):
                    host = mock.Mock(
                        dry=False, home=self.cfg, bead=self.bead.id, run_id=f"r{n}", pause_reason=reason,
                        pause_producer=producer, pause_permanence=policy.permanence, retry_after=0.0, asked=False
                    )
                    host.clock.now.return_value = 100
                    with mock.patch("taskloop.app.pipeline.closing.beadtools.peek", return_value=self.bead):
                        Closer(host, mock.Mock(), ClosingAsks(host.home), ClosingAsks(host.home)).pause(oc.make(Kind.PAUSE_LANE, "paused"))
                    rec = store.return_value.put.call_args.args[0]
                    assert rec.attempts == {pauses.attempt_key(reason, producer): n + 1}
                    assert rec.permanence == ("transient" if n < policy.max_attempts else "needs_owner")
                    assert host.asked == (n == policy.max_attempts)
                    assert host.ask_flow.raise_ask.call_count == int(n == policy.max_attempts)
                    store.return_value.get.return_value = rec

    def test_faults_asks_and_owner_holds_do_not_acquire_retry_records(self):
        for kind in (*FAULTS, *ASKS, Kind.WAIT_ASK, Kind.OWNER_PARK):
            with self.subTest(kind=kind), mock.patch.object(parks, "ParkStore") as store:
                through_change(store)
                with pytest.raises(ValueError, match="no park wake for kind"):
                    parks.paused(self.cfg, self.bead, kind, "r1", 100, reason="worker_failed")
                store.assert_not_called()

    def test_question_close_keeps_its_original_record_fields(self):
        with mock.patch.object(parks, "ParkStore") as store:
            through_change(store)
            store.return_value.get.return_value = None
            parks.ended(self.cfg, self.bead, Kind.ASK_STUCK, "r1", 100)
            store.return_value.put.assert_called_once_with(Park(bead=self.bead.id, hash=text_hash(self.bead), runs=1, run="r1", t=100))

    def test_transient_pause_still_records_backoff_and_predicted_lower_bound(self):
        with mock.patch.object(parks, "ParkStore") as store:
            through_change(store)
            store.return_value.get.return_value = None
            rec = parks.paused(self.cfg, self.bead, Kind.PAUSE_LANE, "r1", 100, reason="rate_limited",
                               not_before=900, draw=lambda: 0.5, permanence="transient")
            assert rec is not None
            assert (
                (rec.reason, rec.permanence, rec.retry_at, rec.attempts)
                == ("rate_limited", "transient", 900, {"delegate:rate_limited": 1})
            )
            store.return_value.put.assert_called_once_with(rec)

    def test_noop_is_parked_for_the_owner_without_a_timer(self):
        with mock.patch.object(parks, "ParkStore") as store:
            through_change(store)
            store.return_value.get.return_value = None
            rec = parks.paused(self.cfg, self.bead, Kind.NOOP, "r1", 100, draw=lambda: 0.5)
            assert rec is not None
            assert (rec.reason, rec.permanence, rec.retry_at) == ("plan_noop", "needs_owner", 0)
            assert park.verdict(rec, self.bead, now=10_000_000) is not None
            assert park.verdict(rec, self.bead, answered=True) is None
            assert park.verdict(rec, self.bead.replace(description="Implement this")) is None
            store.return_value.put.assert_called_once_with(rec)
            parks.ended(self.cfg, self.bead, Kind.NOOP, "r1", 100)
            store.return_value.drop.assert_not_called()
