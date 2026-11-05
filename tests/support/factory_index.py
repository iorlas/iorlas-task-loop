"""Prepare fixture runs through the production indexer before asking a view to read."""

from taskloop.contracts import beadrows, factorydb
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.index import Indexer


def ingest(cfg, now):
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    with Indexer(cfg, clock=lambda: now) as index:
        while not index.pass_once():
            pass


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
