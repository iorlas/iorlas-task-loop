"""The factory.db parts the dashboard indexer, readers and owner writes use."""
from tlkernel.dbparts import Part
from tlkernel.factoryparts import ASKS, DASH, KV, PIPELINE, SLOTS

DASH_PARTS: tuple[Part, ...] = (DASH, PIPELINE, SLOTS, ASKS, KV)
