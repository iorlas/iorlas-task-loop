"""The plan section's restart keep rule."""
import pytest
from tlkernel import wire
from tlkernel.checkpoint import RunState

from tlwork.plan.restart import keep


@pytest.mark.parametrize("name", wire.names(RunState))
def test_keep_table(name: str):
    state = RunState()
    fields = ("extra", "rebase_resets", "brief_hash", "snap", "planner_ref")
    kept = keep(state)
    assert (name in kept) == (name in fields)
    if name in fields:
        assert kept[name] is getattr(state, name)
