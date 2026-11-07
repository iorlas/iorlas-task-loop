"""A mocked ParkStore whose `change` does what the real one does with the mock's `get` and `put`: read, apply, write."""
from unittest import mock


def through_change(store: mock.MagicMock) -> None:
    """`store` is the patched class: `change(bead, fn)` becomes fn(get()) written with put(), so a test keeps asserting on `put`."""
    inst = store.return_value

    def change(_bead, fn):
        rec = fn(inst.get.return_value)
        inst.put(rec)
        return rec

    inst.change.side_effect = change
