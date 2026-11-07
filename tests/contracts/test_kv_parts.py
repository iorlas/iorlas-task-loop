"""Each extracted document is written to its owning table, leaving kv empty."""
import pytest

from taskloop.stores.ticketrows import TicketRows
from taskloop_dash.index import Indexer
from tlkernel import beadrows, factorydb, receipts
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore
from tlkernel.snapshots import ReposIndex


@pytest.fixture
def cfg(tmp_path):
    return ConfigDir(tmp_path)


def assert_row(cfg, table, key):
    con = factorydb.open_rw(cfg.factory_db())
    try:
        assert con.execute(f"SELECT k FROM {table} WHERE k=?", (key,)).fetchone() == (key,)
        assert con.execute("SELECT k FROM kv WHERE k=?", (key,)).fetchone() is None
    finally:
        con.close()


def test_receipts_own_their_rows(cfg):
    con = factorydb.open_rw(cfg.factory_db())
    try:
        with factorydb.begin_immediate(con):
            receipts.put(con, "click", {"ok": True}, 10)
        assert receipts.get(con, "click") == {"ok": True}
    finally:
        con.close()
    assert_row(cfg, "receipt_doc", "receipt.click")


def test_bead_cache_owns_observations_including_empty_listings(cfg):
    con = factorydb.open_rw(cfg.factory_db())
    try:
        with factorydb.begin_immediate(con):
            beadrows.replace_repo(con, "repo", [], 7, 10)
        assert beadrows.observation(con, "repo") == (7, 10, "", 10)
    finally:
        con.close()
    assert_row(cfg, "bead_doc", "beads.repo")


def test_repos_own_the_index(cfg):
    store = ReposStore(cfg)
    store.write(ReposIndex())
    assert store.get() == ReposIndex()
    assert_row(cfg, "repos_doc", "repos")


def test_ticket_counter_survives_an_empty_line(cfg):
    rows = TicketRows(cfg)
    first = rows.take("repo", "test", 1, pid=1, now=10)
    rows.drop("repo", first.seq)
    second = rows.take("repo", "test", 1, pid=1, now=11)
    assert second.seq == first.seq + 1
    assert_row(cfg, "ticket_doc", "slot-seq:repo")


def test_index_owns_the_freshness_stamp_and_clears_it(cfg):
    with Indexer(cfg, clock=lambda: 10) as index:
        assert index.pass_once()
        assert_row(cfg, "index_doc", "index.run.pass")
        index.clear()
        assert index.con.execute("SELECT k FROM index_doc").fetchall() == []
