"""Amendment context belongs to the plan stage and survives resume until cleared."""
from taskloop.app.plan.amend import AmendState
from tlkernel.plancheck import PlanData


def test_defaults():
    state = AmendState()
    assert (state.old_plan, state.text, state.why, state.amended) == (None, "", "", False)


def test_resume_without_text_keeps_existing_text():
    state = AmendState()
    state.text = "earlier change"
    state.amended = True
    plan = PlanData(summary="old", stages=[])
    state.resume_into(plan, "bead changed")
    assert state.old_plan is plan
    assert (state.why, state.text, state.amended) == ("bead changed", "earlier change", True)


def test_resume_with_text_replaces_it_even_when_empty():
    state = AmendState()
    plan = PlanData(summary="old", stages=[])
    state.resume_into(plan, "branch changed", "new change")
    assert state.old_plan is plan
    assert (state.why, state.text) == ("branch changed", "new change")
    state.resume_into(None, "fresh", "")
    assert (state.old_plan, state.why, state.text) == (None, "fresh", "")


def test_clear_resets_all_fields():
    state = AmendState()
    state.resume_into(PlanData(summary="old", stages=[]), "changed", "change")
    state.amended = True
    state.clear()
    assert (state.old_plan, state.text, state.why, state.amended) == (None, "", "", False)
