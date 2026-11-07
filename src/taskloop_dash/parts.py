"""The factory.db parts the dashboard indexer, readers and owner writes use."""
from tlkernel.dbparts import Part
from tlkernel.factoryparts import ASKS, BEADCACHE, DASH, INDEX, PIPELINE, RECEIPT, REPOS, SLOTS

DASH_PARTS: tuple[Part, ...] = (DASH, PIPELINE, ASKS, RECEIPT, BEADCACHE, REPOS, INDEX, SLOTS)
