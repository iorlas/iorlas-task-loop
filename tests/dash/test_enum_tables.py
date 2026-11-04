"""Enum display tables explicitly preserve the formerly implicit empty cases."""
import unittest

from taskloop.contracts.dashenums import Marker, Phase
from taskloop.contracts.enums import Cause, Step, WhyCode
from taskloop_dash.views import columns, phases


class DisplayTables(unittest.TestCase):
    def test_non_visual_steps_have_no_phase(self):
        for step in (Step.RESET, Step.CLOSE, Step.REFLECT):
            self.assertIn(step, phases.STEP_PHASE)
            self.assertIsNone(phases.phase_of(step))

    def test_unspecified_closing_codes_and_causes_have_no_pass_end(self):
        for code in (WhyCode.FAILED, WhyCode.STUCK, WhyCode.CHECK_BEFORE_LAND,
                     WhyCode.HUNG, WhyCode.SCHEMA_INVALID, WhyCode.RESOURCE):
            self.assertEqual(phases.CODE_END[code], "")
        for cause in (Cause.LANE_OUT, Cause.LANE_WAIT, Cause.INVALID_OUTPUT):
            self.assertEqual(phases.CAUSE_END[cause], "")

    def test_passive_markers_preserve_the_current_dot_state(self):
        for marker in (Marker.SOFT_ASK, Marker.PARKED, Marker.NOOP, Marker.READY,
                       Marker.BLOCKED, Marker.DONE):
            self.assertIn(marker, columns.CURRENT_DOT)
            self.assertIsNone(columns.CURRENT_DOT[marker])
            self.assertEqual(columns.dots_of(set(), Phase.PLAN, marker, False)[0].state, "todo")
            self.assertEqual(columns.dots_of({Phase.PLAN}, Phase.PLAN, marker, False)[0].state, "done")
