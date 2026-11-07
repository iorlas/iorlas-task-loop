"""The plan section's restart keep rule."""
import pytest

from taskloop.app.plan.restart import keep
from tlkernel import wire
from tlkernel.checkpoint import RunState


@pytest.mark.parametrize("name", wire.names(RunState))
def test_keep_table(name: str):
    state = RunState()
    fields = ("extra", "rebase_resets", "brief_hash", "snap", "planner_ref")
    kept = keep(state)
    assert (name in kept) == (name in fields)
    if name in fields:
        assert kept[name] is getattr(state, name)
