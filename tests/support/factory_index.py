"""Prepare fixture runs through the production indexer before asking a view to read."""

from taskloop.contracts.paths import ConfigDir
from taskloop_dash.index import Indexer


def ingest(cfg, now):
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    with Indexer(cfg, clock=lambda: now) as index:
        while not index.pass_once():
            pass
