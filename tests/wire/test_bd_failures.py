"""Optional tracker reads keep their fallbacks when bd is unavailable."""
import unittest
from unittest import mock

import support.paths  # noqa: F401

from taskloop.app.wire import asks, brief, doctor, slots
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir


class BdFallbacks(unittest.TestCase):
    def test_priority_defaults_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        with mock.patch.object(slots, "bd_store", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            self.assertEqual(slots.bead_priority("/repo", BeadId("t-1"), who), slots.DEFAULT_PRIO)

    def test_doctor_skips_bead_lint_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        with mock.patch.object(doctor, "bd_store", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            self.assertEqual(doctor.bead_lint_warnings("/repo", who), [])

    def test_brief_omits_slots_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        with mock.patch.object(slots, "bd_store", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            self.assertEqual(brief.slot_lines("/repo", who, 0), ())

    def test_sweep_remains_optional_when_bd_is_missing(self):
        who = Identity(actor="owner", home=".")
        home = mock.Mock(spec=ConfigDir)
        with mock.patch.object(asks, "store"), \
                mock.patch.object(asks.sweeps, "close_stale", side_effect=BdCommandFailure("tl: bd is not on PATH")):
            self.assertEqual(asks.sweep("close", who, home), [])
