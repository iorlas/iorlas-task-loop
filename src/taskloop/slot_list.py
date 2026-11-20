"""The slot list: the adopted slots and what holds them, read-only; no slots is a successful list."""

from dataclasses import dataclass

from taskloop.attempt_reads import StoreUnavailable
from taskloop.operations import Failed
from taskloop.slot_list_store import SlotListStore, SlotRow


@dataclass(frozen=True)
class SlotList:
    rows: tuple[SlotRow, ...]


def list_slots(store: SlotListStore) -> SlotList | Failed:
    try:
        return SlotList(store.slots())
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
