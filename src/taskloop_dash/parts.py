"""The factory.db parts the dashboard indexer, readers and owner writes use."""
from tlkernel.dbparts import Part
from tlkernel.factoryparts import ASKS, BEADCACHE, DASH, INDEX, KV, PIPELINE, RECEIPT, REPOS

DASH_PARTS: tuple[Part, ...] = (DASH, PIPELINE, ASKS, KV, RECEIPT, BEADCACHE, REPOS, INDEX)
