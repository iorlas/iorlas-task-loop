"""Enum display tables explicitly preserve the formerly implicit empty cases."""

from support.case import Case

from taskloop_dash.views import columns, phases
from tlkernel.dashenums import Marker, Phase
from tlkernel.enums import Cause, Step, WhyCode


class DisplayTables(Case):
    def test_non_visual_steps_have_no_phase(self):
        for step in (Step.RESET, Step.CLOSE, Step.REFLECT):
            assert step in phases.STEP_PHASE
            assert phases.phase_of(step) is None

    def test_unspecified_closing_codes_and_causes_have_no_pass_end(self):
        for code in (WhyCode.FAILED, WhyCode.STUCK, WhyCode.CHECK_BEFORE_LAND,
                     WhyCode.HUNG, WhyCode.SCHEMA_INVALID, WhyCode.RESOURCE):
            assert phases.CODE_END[code] == ""
        for cause in (Cause.LANE_OUT, Cause.LANE_WAIT, Cause.INVALID_OUTPUT):
            assert phases.CAUSE_END[cause] == ""

    def test_passive_markers_preserve_the_current_dot_state(self):
        for marker in (Marker.SOFT_ASK, Marker.PARKED, Marker.NOOP, Marker.READY,
                       Marker.BLOCKED, Marker.DONE):
            assert marker in columns.CURRENT_DOT
            assert columns.CURRENT_DOT[marker] is None
            assert columns.dots_of(set(), Phase.PLAN, marker, False)[0].state == "todo"
            assert columns.dots_of({Phase.PLAN}, Phase.PLAN, marker, False)[0].state == "done"
