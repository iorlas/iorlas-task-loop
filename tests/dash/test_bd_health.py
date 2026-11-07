"""Indexer outages retain bead observations; live drawer comments retain their own health."""

import pytest
from support.dashlogs import bead
from support.factory_index import ingest, seed_beads
from support.fakes import FakeBeadStore

from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.index import Indexer
from tlkernel import beadrows, factorydb
from tlkernel.bead import BdError
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId, loop_key
from tltestkit.repos import write_repos

ERROR = "other: database locked\nretry later"


def unreadable(_):
    raise BdFailure(BdError(kind="other", text="database locked\nretry later"))


@pytest.fixture
def board(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    write_repos(cfg / "repos.json", repo)
    store = FakeBeadStore().put(bead("b-1", "Old claim", "in_progress"))
    store.note("b-1", "Old comment")
    now = [1000.0]
    ingest(cfg, now[0])
    seed_beads(cfg, repo, store.beads.values(), now[0])
    env = Env(cfg, home=tmp_path, ports=Ports(store=lambda _: store), clock=lambda: now[0])
    dash = Dash(env)
    try:
        yield dash, str(repo), store, now
    finally:
        dash.reads.wait()
        dash.reads.wake.close()


def test_comment_failure_keeps_rows_and_time_then_retries(board):
    dash, repo, store, now = board
    reader, bid = dash.beads, BeadId("b-1")
    old = reader.comments(repo, bid)
    now[0] += 16
    with store.stub(comments_fn=unreadable):
        assert reader.comments(repo, bid) == old
        assert reader.health(repo, bid) == (1000, ERROR)
        now[0] += 1
        assert reader.comments(repo, bid) == old
        assert reader.health(repo, bid) == (1000, ERROR)
    assert reader.comments(repo, bid) == old
    assert reader.health(repo, bid) == (1017, "")
    assert reader.health(repo) == (1000, "")


def test_cold_comment_failure_has_no_success_time_and_retries(board):
    dash, repo, store, _ = board
    with store.stub(comments_fn=unreadable):
        assert dash.beads.comments(repo, BeadId("b-1")) == []
        assert dash.beads.health(repo, "b-1") == (None, ERROR)
    assert dash.beads.comments(repo, BeadId("b-1"))
    assert dash.beads.health(repo, "b-1") == (1000, "")


def refresh(dash, repo):
    env = dash.env
    with Indexer(env.config, clock=env.clock, repos=lambda: [repo], store_of=env.ports.store) as index:
        assert index.beads is not None
        index.beads.refresh(index.con, repo, env.clock(), force=True)


def test_snapshot_publishes_indexer_failure_and_recovery(board):
    dash, repo, store, now = board
    before = dash.reads.snapshot()
    now[0] += 1
    with store.stub(find_fn=unreadable):
        refresh(dash, repo)
    code, _, _ = dash.reads.get("/api/snapshot", {"since": before.version, "wait": "20"})
    assert code == 200
    failed = dash.reads.snapshot()
    assert failed.beads == before.beads
    assert (failed.projects[0].bd_ok_at, failed.projects[0].bd_error) == (1000, ERROR)
    assert failed.version != before.version
    now[0] += 1
    refresh(dash, repo)
    assert dash.reads.get("/api/snapshot", {"since": failed.version, "wait": "20"})[0] == 200
    recovered = dash.reads.snapshot()
    assert (recovered.projects[0].bd_ok_at, recovered.projects[0].bd_error) == (1002, "")


def test_detail_publishes_comment_failure_and_recovers(board):
    dash, repo, store, now = board
    before = dash.reads.bead(loop_key(repo), "b-1")
    assert before is not None
    now[0] += 16
    with store.stub(comments_fn=unreadable):
        dash.reads.bead(loop_key(repo), "b-1")
        dash.reads.wait()
        failed = dash.reads.bead(loop_key(repo), "b-1")
    assert failed is not None
    assert (failed.comments, failed.bd_ok_at, failed.bd_error) == (before.comments, 1000, ERROR)
    now[0] += 4
    dash.reads.bead(loop_key(repo), "b-1")
    dash.reads.wait()
    recovered = dash.reads.bead(loop_key(repo), "b-1")
    assert recovered is not None
    assert (recovered.bd_ok_at, recovered.bd_error) == (1020, "")


def test_fresh_reader_preserves_original_success_time(board):
    dash, repo, store, now = board
    now[0] += 61
    fresh = Dash(Env(dash.env.config.root, ports=dash.env.ports, clock=lambda: now[0]))
    with store.stub(find_fn=unreadable):
        assert fresh.beads.beads_of(repo)
        assert fresh.beads.health(repo) == (1000, "")
        refresh(dash, repo)
        assert fresh.beads.beads_of(repo)
        assert fresh.beads.health(repo) == (1000, ERROR)


@pytest.mark.parametrize("error", [OSError("bd missing"), ValueError("invalid JSON"),
                                  UnicodeDecodeError("utf8", b"\xff", 0, 1, "invalid")])
def test_indexer_and_comment_errors_preserve_observations(board, error):
    dash, repo, store, now = board
    rows = dash.beads.beads_of(repo)
    comments = dash.beads.comments(repo, BeadId("b-1"))
    now[0] += 61

    def fail(_):
        raise error

    with store.stub(find_fn=fail, comments_fn=fail):
        refresh(dash, repo)
        assert dash.beads.beads_of(repo) == rows
        assert dash.beads.comments(repo, BeadId("b-1")) == comments
    for bid in ("", "b-1"):
        assert dash.beads.health(repo, bid) == (1000, str(error))


def test_repo_health_is_separate_from_each_comment_read(board):
    dash, repo, store, _ = board
    other = repo + "-other"
    seed_beads(dash.env.config, other, store.beads.values(), 1000)
    dash.beads.comments(repo, BeadId("b-2"))
    con = factorydb.open_rw(dash.env.config.factory_db())
    assert con is not None
    try:
        with factorydb.begin_immediate(con):
            beadrows.set_error(con, loop_key(repo), ERROR, 1001)
    finally:
        con.close()
    assert dash.beads.health(repo) == (1000, ERROR)
    assert dash.beads.health(other) == (1000, "")
    assert dash.beads.health(repo, "b-2") == (1000, "")
