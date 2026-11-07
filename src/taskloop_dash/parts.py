"""The factory.db parts the dashboard indexer, readers and owner writes use."""
from tlkernel.dbparts import Part
from tlkernel.factoryparts import ASKS, DASH, KV, PIPELINE

DASH_PARTS: tuple[Part, ...] = (DASH, PIPELINE, ASKS, KV)
