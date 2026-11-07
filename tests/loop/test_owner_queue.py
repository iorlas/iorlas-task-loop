"""Owner queue operations return the exact display lines without printing."""
from unittest.mock import Mock

import pytest

from taskloop.app.loop.queue import owner_queue
from tlkernel import pickset
from tlkernel.bead import Bead
from tlkernel.beadsport import BdError, BdFailure
from tlkernel.ids import BeadId


@pytest.mark.parametrize("op", ["add", "remove"])
def test_missing_ids_refuses_before_accessing_store(op):
    store, now = Mock(), Mock()
    assert owner_queue(op, [], store, now) == (2, [f"tl: queue {op}: name at least one bead"])
    assert store.mock_calls == []
    now.assert_not_called()


def test_list_orders_members_and_truncates_titles():
    store = Mock()
    store.find.return_value = [
        Bead(id=BeadId("t-1"), title="x" * 80, status="blocked", labels=[pickset.LABEL], metadata={pickset.AT: "2"}),
        Bead(id=BeadId("t-2"), title="second", status="open", labels=[pickset.LABEL], metadata={pickset.AT: "1"}),
    ]
    assert owner_queue("list", [], store, Mock()) == (0, ["1. t-2  open  second", f"2. t-1  blocked  {'x' * 70}"])


def test_missing_bead_keeps_earlier_add_and_stops():
    store = Mock()
    store.show.side_effect = [Bead(id=BeadId("t-1"), title="first", status="open"), None]
    assert owner_queue("add", ["t-1", "t-2", "t-3"], store, lambda: 1.0) == (1, ["tl: no such bead t-2"])
    store.add_label.assert_called_once_with("t-1", pickset.LABEL)
    assert store.update.call_args.args[1].set_metadata == {pickset.AT: "1000"}
    store.find.assert_not_called()


@pytest.mark.parametrize("error", [BdFailure(BdError(kind="other", text="unavailable")), ValueError("invalid")])
def test_store_failures_return_error_line(error):
    store = Mock()
    store.find.side_effect = error
    assert owner_queue("list", [], store, Mock()) == (1, [f"tl: {error}"])


def test_remove_clears_queue_order_and_reports_empty():
    store = Mock()
    store.find.return_value = []
    assert owner_queue("remove", ["t-1"], store, Mock()) == (0, ["queue empty: the loop takes any ready bead"])
    store.remove_label.assert_called_once_with("t-1", pickset.LABEL)
    assert store.update.call_args.args[1].unset_metadata == [pickset.AT]
