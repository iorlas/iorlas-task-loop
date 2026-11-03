"""Broken slots recover on successful probes, without clock holds."""
from unittest.mock import patch

import support.paths  # noqa: F401

from slots.test_slot_pool import Rig
from taskloop.app.slots import aside
from taskloop.app.slots.marks import mark_held
from taskloop.app.slots.pool import Slot
from taskloop.contracts.ports import BeadPatch
from taskloop.contracts.slots import SlotFail


class Aside(Rig):
    def setUp(self):
        super().setUp()
        self.env.cfg = self.env.cfg.replace(count=1)

    def pending(self):
        self.bd.update(self.slot().slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))

    def test_failed_probes_exclude_slot_and_retry_without_advancing_clock(self):
        self.pending()
        now = self.t[0]
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")) as probe:
            for _ in range(3):
                self.assertIsNone(self.pool.take_any("work"))
                self.assertIsNone(self.slot().hold())
                self.assertEqual(self.slot().slot_bead().status, "open")
            self.assertEqual(probe.call_count, 3)
        self.assertEqual(self.t[0], now)
        self.assertEqual(self.slot().slot_bead().metadata["aside_probe"], "pending")

    def test_successful_probe_returns_slot_immediately(self):
        self.pending()
        with patch.object(Slot, "ready_for") as probe, patch.object(aside, "setup") as setup:
            self.assertIsNotNone(self.pool.take_any("work"))
        probe.assert_called_once_with("")
        setup.assert_called_once()
        assert setup.call_args is not None
        self.assertTrue(setup.call_args.kwargs["force"])
        bead = self.slot().slot_bead()
        self.assertEqual(bead.status, "in_progress")
        self.assertNotIn("aside_level", bead.metadata)
        self.assertNotIn("aside_probe", bead.metadata)

    def test_healthy_slot_does_not_probe(self):
        with patch.object(Slot, "ready_for") as probe:
            self.assertIsNotNone(self.pool.take_any("work"))
        probe.assert_not_called()

    def test_failed_setup_keeps_probe_pending(self):
        self.pending()
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup", side_effect=SlotFail("slot_broken", "setup failed")):
            self.assertIsNone(self.pool.take_any("work"))
        self.assertEqual(self.slot().slot_bead().metadata["aside_probe"], "pending")

    def test_busy_slot_is_never_reset_by_probe(self):
        self.pending()
        self.slot().take_locked("another worker")
        with patch.object(Slot, "ready_for") as probe:
            self.assertIsNone(self.pool.take_any("work"))
        probe.assert_not_called()

    def test_legacy_automatic_hold_does_not_delay_recovery(self):
        self.slot().take("old automatic hold")
        mark_held(self.env, self.slot().slot_bead().id, "old automatic hold", self.t[0] + 720 * 60)
        self.pending()
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup"):
            self.assertIsNotNone(self.pool.take_any("work"))
        self.assertIsNone(self.slot().hold())
