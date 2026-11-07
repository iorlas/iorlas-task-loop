"""The plan stage's once-per-run flags live in PlanState, one object the engine holds as `engine.plan_state`, and start unset."""
from tlwork.plan.state import PlanState


def test_a_run_starts_with_no_send_back_used_and_no_cap_granted():
    s = PlanState()
    assert (s.cap_granted, s.assumed, s.decided, s.visual_back) == (False, False, False, False)
