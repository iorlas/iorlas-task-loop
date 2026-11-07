"""Broken slots recover on successful probes, without clock holds."""
from unittest.mock import patch

from tlkernel.beadsport import BeadPatch
from tlkernel.slots import SlotFail
from tlslots import aside
from tlslots.marks import mark_held
from tlslots.pool import Slot
from tlslots.testing import Rig


class Aside(Rig):
    def setup_method(self):
        super().setup_method()
        self.env.cfg = self.env.cfg.replace(count=1)

    def pending(self):
        self.bd.update(self.slot().slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))

    def test_a_failed_probe_excludes_the_slot_until_the_next_interval(self):
        self.pending()
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")) as probe:
            for _ in range(3):
                assert self.pool.take_any("work") is None
                assert self.slot().hold() is None
                assert self.slot().slot_bead().status == "open"
            assert probe.call_count == 1  # the first pass probed; the others are before the 60 minutes are up
            assert self.slot().slot_bead().metadata["aside_level"] == "1"
            self.t[0] += 61 * 60
            assert self.pool.take_any("work") is None
            assert probe.call_count == 2
        assert self.slot().slot_bead().metadata["aside_probe"] == "pending"

    def test_successful_probe_returns_slot_immediately(self):
        self.pending()
        with patch.object(Slot, "ready_for") as probe, patch.object(aside, "setup") as setup:
            assert self.pool.take_any("work") is not None
        probe.assert_called_once_with("")
        setup.assert_called_once()
        assert setup.call_args is not None
        assert setup.call_args.kwargs["force"]
        bead = self.slot().slot_bead()
        assert bead.status == "in_progress"
        assert not {"aside_level", "aside_probe", "aside_until"} & set(bead.metadata)

    def test_healthy_slot_does_not_probe(self):
        with patch.object(Slot, "ready_for") as probe:
            assert self.pool.take_any("work") is not None
        probe.assert_not_called()

    def test_failed_setup_keeps_probe_pending(self):
        self.pending()
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup", side_effect=SlotFail("slot_broken", "setup failed")):
            assert self.pool.take_any("work") is None
        assert self.slot().slot_bead().metadata["aside_probe"] == "pending"

    def test_busy_slot_is_never_reset_by_probe(self):
        self.pending()
        self.slot().take_locked("another worker")
        with patch.object(Slot, "ready_for") as probe:
            assert self.pool.take_any("work") is None
        probe.assert_not_called()

    def test_legacy_automatic_hold_does_not_delay_recovery(self):
        self.slot().take("old automatic hold")
        mark_held(self.env, self.slot().slot_bead().id, "old automatic hold", self.t[0] + 720 * 60)
        self.pending()
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup"):
            assert self.pool.take_any("work") is not None
        assert self.slot().hold() is None
