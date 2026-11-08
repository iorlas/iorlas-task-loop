"""The land section's restart keep rule."""
import pytest
from tlkernel import wire
from tlkernel.checkpoint import RunState

from tlland.section import keep, pin_validation


@pytest.mark.parametrize("name", wire.names(RunState))
def test_keep_table(name: str):
    state = RunState()
    fields = ("pending_land_validation", "leftovers", "followup_ids")
    kept = keep(state)
    assert (name in kept) == (name in fields)
    if name in fields:
        assert kept[name] is getattr(state, name)


@pytest.mark.parametrize(("pending", "expected"), [("red", ("land-verify-red", "red")), ("", ("write", "feedback"))])
def test_pin_validation(pending: str, expected: tuple[str, str]):
    assert pin_validation(RunState(pending_land_validation=pending), "write", "feedback") == expected
