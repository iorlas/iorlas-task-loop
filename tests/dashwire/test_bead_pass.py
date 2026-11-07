"""The indexer lists bd only when due; server reads are exclusively database reads."""

import os
from pathlib import Path

import pytest
from support.fakes import FakeBeadStore

from tldash.env import Env, Ports
from tldash.index import Indexer, reindex
from tldash.readers.beads import Beads
from tldash.readers.records import Records
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure, BeadQuery
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir


class CountingStore(FakeBeadStore):
    def __init__(self):
        super().__init__()
        self.finds = 0

    def find(self, query: BeadQuery) -> list[Bead]:
        self.finds += 1
        assert query.include_closed
        return super().find(query)


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    store = CountingStore()
    store.put(Bead(id=BeadId("b-1"), title="Title", status="closed"))
    now = [1000.0]
    env = Env(tmp_path / "cfg", clock=lambda: now[0], ports=Ports(store=lambda _: store))
    return env, str(repo), store, now


def marker(repo):
    path = Path(repo) / ".beads" / "last-touched"
    path.parent.mkdir(exist_ok=True)
    path.touch()
    return path


def index_of(env, repo):
    return Indexer(env.config, clock=env.clock, repos=lambda: [repo], store_of=env.ports.store)


def test_unchanged_marker_skips_bd_even_on_a_cold_indexer(world):
    env, repo, store, now = world
    marker(repo)
    with index_of(env, repo) as index:
        index.pass_once()
        index.pass_once()
    now[0] += 10000
    with index_of(env, repo) as index:
        index.pass_once()
    assert store.finds == 1
    reader = Beads(env, Records(env))
    assert reader.beads_of(repo)[0]["status"] == "closed"
    assert reader.health(repo) == (1000, "")


def test_changed_marker_lists_once(world):
    env, repo, store, _ = world
    path = marker(repo)
    with index_of(env, repo) as index:
        index.pass_once()
        stamp = path.stat().st_mtime_ns + 1
        os.utime(path, ns=(stamp, stamp))
        index.pass_once()
        index.pass_once()
    assert store.finds == 2


def fail(_):
    raise BdFailure(BdError(kind="other", text="database locked"))


def test_failure_keeps_rows_and_exposes_health_then_recovers(world):
    env, repo, store, now = world
    path = marker(repo)
    reader = Beads(env, Records(env))
    with index_of(env, repo) as index:
        index.pass_once()
        old = reader.beads_of(repo)
        stamp = path.stat().st_mtime_ns + 1
        os.utime(path, ns=(stamp, stamp))
        now[0] += 1
        with store.stub(find_fn=fail):
            index.pass_once()
        assert reader.beads_of(repo) == old
        assert reader.health(repo) == (1000, "other: database locked")
        index.pass_once()
    assert reader.health(repo) == (1001, "")


def test_no_marker_refreshes_at_most_once_per_minute_across_restarts(world):
    env, repo, store, now = world
    with index_of(env, repo) as index:
        index.pass_once()
        now[0] += 59
        index.pass_once()
    with index_of(env, repo) as index:
        index.pass_once()
        assert store.finds == 1
        now[0] += 1
        index.pass_once()
        assert store.finds == 2


def test_no_marker_throttles_failed_attempts_too(world):
    env, repo, store, now = world
    with store.stub(find_fn=fail), index_of(env, repo) as index:
        index.pass_once()
        now[0] += 59
        index.pass_once()
        assert store.finds == 1
        now[0] += 1
        index.pass_once()
    assert store.finds == 2


def test_server_reader_never_lists_bd_even_with_missing_db(world):
    env, repo, store, _ = world
    reader = Beads(env, Records(env))
    with store.stub(find_fn=lambda _: pytest.fail("server listed bd")):
        assert reader.beads_of(repo) == []
        assert reader.health(repo) == (None, "")
    with index_of(env, repo) as index:
        index.pass_once()
    fresh = Beads(env, Records(env))
    with store.stub(find_fn=lambda _: pytest.fail("server listed bd")):
        assert fresh.beads_of(repo)
        assert fresh.health(repo) == (1000, "")


def test_empty_success_is_marker_gated(world):
    env, repo, store, _ = world
    marker(repo)
    store.beads.clear()
    for _ in range(2):
        with index_of(env, repo) as index:
            index.pass_once()
    assert store.finds == 1


def test_round_robin_bounds_each_pass_and_reindex_refreshes_all(world, tmp_path):
    env, repo, store, _ = world
    other = tmp_path / "other"
    other.mkdir()
    def repos():
        return [repo, str(other)]

    marker(repo)
    marker(other)
    with Indexer(env.config, clock=env.clock, repos=repos, store_of=env.ports.store) as index:
        index.pass_once(budget=0)
        assert store.finds == 1
        index.pass_once(budget=0)
        assert store.finds == 2
    reindex(ConfigDir(env.config.root), clock=env.clock, repos=repos, store_of=env.ports.store)
    assert store.finds == 4
