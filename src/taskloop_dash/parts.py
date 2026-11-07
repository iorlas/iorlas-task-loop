"""The factory.db parts the dashboard indexer, readers and owner writes use."""
from taskloop.contracts.dbparts import Part
from taskloop.contracts.factoryparts import ASKS, DASH, KV, PIPELINE, SLOTS

DASH_PARTS: tuple[Part, ...] = (DASH, PIPELINE, SLOTS, ASKS, KV)
