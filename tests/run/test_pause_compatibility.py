"""Transient retry scheduling must not change existing owner, ask or infrastructure closes."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.asks import parks
from taskloop.app.run.closer import Closer
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import ASKS, FAULTS, Kind
from taskloop.contracts.parks import Park
from taskloop.domain import outcome as oc
from taskloop.domain.beads import park
from taskloop.domain.beads.park import text_hash


class PauseCompatibility(unittest.TestCase):
    def setUp(self):
        self.bead = Bead(id=BeadId("t-1"), title="work", status="open")
        self.cfg = mock.Mock()

    def test_owner_and_unknown_reasons_do_not_create_a_park_or_ask(self):
        for reason in (
            "logged_out",
            "secrets",
            "credit_exhausted",
            "setup",
            "contract_violation",
            "engine_only_unenforced",
            "new_vendor_reason",
        ):
            with self.subTest(reason=reason), mock.patch.object(parks, "ParkStore") as store:
                host = mock.Mock(
                    dry=False, home=self.cfg, bead=self.bead.id, run_id="r1", pause_reason=reason, retry_after=0.0, asked=False
                )
                host.clock.now.return_value = 100
                with mock.patch("taskloop.app.run.closer.beadtools.peek", return_value=self.bead):
                    Closer(host, mock.Mock()).pause(oc.make(Kind.PAUSE_LANE, "paused"))
                self.assertEqual((host.retry_after, host.asked, host.pause_reason), (0, False, reason))
                host.ask_flow.raise_ask.assert_not_called()
                store.assert_not_called()

    def test_faults_asks_and_owner_holds_do_not_acquire_retry_records(self):
        for kind in (*FAULTS, *ASKS, Kind.WAIT_ASK, Kind.OWNER_PARK):
            with self.subTest(kind=kind), mock.patch.object(parks, "ParkStore") as store:
                # Even a transient delegate reason must not override the outcome's existing handling.
                self.assertIsNone(parks.paused(self.cfg, self.bead, kind, "r1", 100, reason="worker_failed"))
                store.assert_not_called()

    def test_question_close_keeps_its_original_record_fields(self):
        with mock.patch.object(parks, "ParkStore") as store:
            store.return_value.get.return_value = None
            parks.ended(self.cfg, self.bead, Kind.ASK_STUCK, "r1", 100)
            store.return_value.put.assert_called_once_with(Park(bead=self.bead.id, hash=text_hash(self.bead), runs=1, run="r1", t=100))

    def test_transient_pause_still_records_backoff_and_predicted_lower_bound(self):
        with mock.patch.object(parks, "ParkStore") as store:
            store.return_value.get.return_value = None
            rec = parks.paused(self.cfg, self.bead, Kind.PAUSE_LANE, "r1", 100, reason="rate_limited", not_before=900, draw=lambda: 0.5)
            assert rec is not None
            self.assertEqual(
                (rec.reason, rec.permanence, rec.retry_at, rec.attempts), ("rate_limited", "transient", 900, {"rate_limited": 1})
            )
            store.return_value.put.assert_called_once_with(rec)

    def test_noop_is_parked_for_the_owner_without_a_timer(self):
        with mock.patch.object(parks, "ParkStore") as store:
            store.return_value.get.return_value = None
            rec = parks.paused(self.cfg, self.bead, Kind.NOOP, "r1", 100, draw=lambda: 0.5)
            assert rec is not None
            self.assertEqual((rec.reason, rec.permanence, rec.retry_at), ("plan_noop", "needs_owner", 0))
            self.assertIsNotNone(park.verdict(rec, self.bead, now=10_000_000))
            self.assertIsNone(park.verdict(rec, self.bead, answered=True))
            self.assertIsNone(park.verdict(rec, self.bead.replace(description="Implement this")))
            store.return_value.put.assert_called_once_with(rec)
            parks.ended(self.cfg, self.bead, Kind.NOOP, "r1", 100)
            store.return_value.drop.assert_not_called()
