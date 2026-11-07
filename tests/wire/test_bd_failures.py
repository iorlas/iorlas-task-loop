"""Optional tracker reads keep their fallbacks when bd is unavailable."""
from unittest import mock

from taskloop.app.doctor import setup_checks
from taskloop.app.wire import asks, brief, slots
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlslots.env import DEFAULT_PRIO
from tltestkit.case import Case


class BdFallbacks(Case):
    def test_priority_defaults_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        with mock.patch.object(slots, "bd_store", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            assert slots.bead_priority("/repo", BeadId("t-1"), who) == DEFAULT_PRIO

    def test_doctor_skips_bead_lint_when_bd_is_missing(self):
        store = mock.Mock(side_effect=BdCommandFailure("tl: bd is not on PATH"))
        assert setup_checks.bead_lint_warnings("/repo", store) == []

    def test_brief_omits_slots_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        with mock.patch.object(slots, "slot_table", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            assert brief.slot_lines("/repo", who, 0, mock.Mock()) == ()

    def test_sweep_remains_optional_when_bd_is_missing(self, workdir):
        who = Identity(actor="owner", home=".")
        home = ConfigDir(workdir)
        with mock.patch.object(asks, "store"), \
                mock.patch.object(asks.sweeps, "close_stale", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            assert asks.sweep("close", who, home) == []
