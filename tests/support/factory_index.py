"""Prepare fixture runs through the production indexer before asking a view to read."""

from support.waits import settle
from taskloop_dash.index import Indexer
from tlkernel import beadrows, factorydb
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir


def ingest(cfg, now):
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    with Indexer(cfg, clock=lambda: now) as index:
        settle(index)


def seed_beads(cfg, repo, beads, now):
    """Publish fixture beads through the projection contract, without asking the dashboard to list bd."""
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    cfg.root.mkdir(parents=True, exist_ok=True)
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    try:
        with factorydb.begin_immediate(con):
            beadrows.replace_repo(con, loop_key(repo), [beadrows.row_of(bead) for bead in beads], None, now)
    finally:
        con.close()
