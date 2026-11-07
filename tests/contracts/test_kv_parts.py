"""Each extracted document is written to its owning table, leaving kv empty."""
import pytest
from support.narrow import must

from taskloop.stores.real import real_stores
from taskloop.stores.ticketrows import TicketRows
from taskloop_dash.index import Indexer
from tlkernel import beadrows, factorydb, receipts, rundocs
from tlkernel.checks import Durations
from tlkernel.flakes import FlakeLog, FlakeRow
from tlkernel.paths import ConfigDir
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.rowstores import ReposStore
from tlkernel.run import HandoffMirror, RunCounters
from tlkernel.snapshots import ReposIndex


@pytest.fixture
def cfg(tmp_path):
    return ConfigDir(tmp_path)


def assert_row(cfg, table, key):
    con = must(factorydb.open_rw(cfg.factory_db()))
    try:
        assert con.execute(f"SELECT k FROM {table} WHERE k=?", (key,)).fetchone() == (key,)
        assert con.execute("SELECT k FROM kv WHERE k=?", (key,)).fetchone() is None
    finally:
        con.close()


def test_receipts_own_their_rows(cfg):
    con = must(factorydb.open_rw(cfg.factory_db()))
    try:
        with factorydb.begin_immediate(con):
            receipts.put(con, "click", {"ok": True}, 10)
        assert receipts.get(con, "click") == {"ok": True}
    finally:
        con.close()
    assert_row(cfg, "receipt_doc", "receipt.click")


def test_bead_cache_owns_observations_including_empty_listings(cfg):
    con = must(factorydb.open_rw(cfg.factory_db()))
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


def test_queue_owns_entries_and_tree_assertion_state(cfg):
    stores = real_stores(cfg)
    queue = stores.queue.of("repo")
    state = stores.queue_state.of("repo")
    queue.write(QueueDoc(last_base="main"))
    state.write(QueueState(frozen=True))
    assert queue.need() == QueueDoc(last_base="main")
    assert state.need() == QueueState(frozen=True)
    assert_row(cfg, "queue_doc", "queue:repo")
    assert_row(cfg, "queue_doc", "queue-state:repo")


def test_flake_owns_the_score_log(cfg):
    doc = real_stores(cfg).flakes.of("repo")
    log = FlakeLog(rows=[FlakeRow(test="test_flaky", t=10, how="rerun")])
    doc.write(log)
    assert doc.need() == log
    assert_row(cfg, "flake_doc", "flakes:repo")
def test_run_documents_and_once_notes_live_in_run_doc(cfg):
    counters = RunCounters(elapsed=1, waited=0, cost=0, stats={}, sessions=[], write_rounds=[], node_n=0)
    for store in (rundocs.pause(cfg, "r_1"), rundocs.reexec(cfg, "r_1")):
        store.write(counters)
        assert store.get() == counters
        assert_row(cfg, "run_doc", store.k)
    mirror = HandoffMirror()
    rundocs.handoff(cfg, "r_1").write(mirror)
    assert rundocs.handoff(cfg, "r_1").get() == mirror
    assert_row(cfg, "run_doc", "run:r_1:handoff")
    stamp = rundocs.stamped("inputs")
    rundocs.prepare_stamp(cfg, "r_1").write(stamp)
    assert rundocs.prepare_stamp(cfg, "r_1").get() == stamp
    assert_row(cfg, "run_doc", "run:r_1:prepare")
    assert rundocs.once(cfg, "r_1", "note")
    assert not rundocs.once(cfg, "r_1", "note")
    assert_row(cfg, "run_doc", "run:r_1:once:note")
    assert rundocs.once(cfg, "rx1", "note")
    rundocs.forget(cfg, "r_1")
    con = must(factorydb.open_rw(cfg.factory_db()))
    try:
        assert con.execute("SELECT k FROM run_doc").fetchall() == [("run:rx1:once:note",)]
    finally:
        con.close()


def test_durations_live_in_duration_doc(cfg):
    store = rundocs.durations(cfg).of("repo")
    store.write(Durations())
    assert store.get() == Durations()
    assert_row(cfg, "duration_doc", "durations:repo")
