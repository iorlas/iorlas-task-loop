"""Doctor preserves slot finding order and tolerates unavailable optional reads."""
from unittest import mock

import pytest

from taskloop.app.doctor.setup_checks import slot_warnings
from tlkernel.beadsport import BdError, BdFailure
from tlkernel.slots import SlotTable, SlotView


def test_slot_findings_keep_dead_then_excess_then_liveness_order():
    table = SlotTable(configured=1, source="origin/main", source_sha="123456789", slots=[
        SlotView(id="s1", state="dead", idle_why="gone"),
        SlotView(id="s2", state="claimed", beyond_count=True),
        SlotView(id="s3", state="free", beyond_count=True),
        SlotView(id="s4", state="retiring", beyond_count=True),
    ])
    env = mock.Mock(return_value="context")
    look = mock.Mock(return_value=["slot stall: waiting"])
    assert slot_warnings(lambda: table, env, look) == (
        "slots: 1 configured from origin/main 1234567; s1 dead, s2 claimed, s3 free, s4 retiring",
        ["slot s1 is dead: gone", "slot s2 is above slots.count 1 and still claimed", "slot stall: waiting"],
    )
    env.assert_called_once_with()
    look.assert_called_once_with("context")


@pytest.mark.parametrize("failure", [SystemExit("unavailable"), OSError("unavailable"),
                                     ValueError("unavailable"), BdFailure(BdError(kind="other", text="unavailable"))])
def test_unreadable_slot_table_skips_liveness(failure):
    table = mock.Mock(side_effect=failure)
    env, look = mock.Mock(), mock.Mock()
    assert slot_warnings(table, env, look) == (f"slots: not read ({failure})", [])
    env.assert_not_called()
    look.assert_not_called()


def test_empty_slots_and_optional_liveness_failure():
    table = SlotTable(configured=0, source="worktree", slots=[])
    look = mock.Mock(side_effect=OSError("unavailable"))
    expected = ("slots: 0 configured from worktree; none", [])
    assert slot_warnings(lambda: table, None, look) == expected
    look.assert_not_called()
    assert slot_warnings(lambda: table, lambda: "context", look) == expected
