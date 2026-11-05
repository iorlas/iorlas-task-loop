"""Snapshot long-polls share builds and spend idle time only on the wake counter."""

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from taskloop.contracts.paths import ConfigDir
from taskloop_dash.api.reads import Reads
from taskloop_dash.app import Dash
from taskloop_dash.env import Env
from taskloop_dash.readers.wake import Wake
from taskloop_dash.views import snapshot
from taskloop_dash.views.world import World


class Clock:
    """Each simulated request thread owns its elapsed time; no wall-clock sleeps."""

    def __init__(self) -> None:
        self.times: dict[int, float] = {}
        self.lock = threading.Lock()
        self.on_sleep: Callable[[], None] = lambda: None

    def __call__(self) -> float:
        with self.lock:
            return self.times.get(threading.get_ident(), 0.0)

    def sleep(self, seconds: float) -> None:
        with self.lock:
            key = threading.get_ident()
            self.times[key] = self.times.get(key, 0.0) + seconds
        self.on_sleep()


class FakeWake(Wake):
    def __init__(self, cfg: ConfigDir, clock: Clock) -> None:
        super().__init__(cfg, clock.sleep, clock)
        self.value = 1
        self.available = True
        self.waits: list[float] = []

    def token(self) -> int | None:
        return self.value if self.available else None

    def wait(self, since: int | None, seconds: float) -> int | None:
        self.waits.append(seconds)
        return super().wait(since, seconds)


@dataclass
class Source:
    builds: int = 0
    revision: int = 0
    error: str = ""

    def world(self) -> World:
        return World(now=0, host="test", version=str(self.revision), projects=[], runs={}, asks={}, database_error=self.error)


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Reads, FakeWake, Clock, Source]:
    clock, source = Clock(), Source()
    reads = Dash(Env(tmp_path, home=tmp_path, clock=clock)).reads
    wake = FakeWake(reads.env.config, clock)
    reads.wake = wake
    monkeypatch.setattr(reads.worlds, "database_error", lambda: source.error)
    monkeypatch.setattr(reads.worlds, "world", source.world)
    original = snapshot.build

    def build(world: World):
        source.builds += 1
        return original(world)

    monkeypatch.setattr(snapshot, "build", build)
    return reads, wake, clock, source


def load(reads: Reads) -> str:
    code, body, headers = reads.get("/api/snapshot", {})
    assert code == 200
    version = json.loads(body)["version"]
    assert headers["ETag"] == f'"{version}"'
    return version


def test_first_request_builds_without_waiting(board) -> None:
    reads, wake, _, source = board
    assert reads.get("/api/snapshot", {"wait": "20"})[0] == 200
    assert source.builds == 1
    assert wake.waits == []


def test_two_idle_tabs_wait_sixty_seconds_without_building(board) -> None:
    reads, wake, clock, source = board
    version = load(reads)
    rendezvous = threading.Barrier(2)

    def tab() -> float:
        start = clock()
        for _ in range(3):
            rendezvous.wait(timeout=2)
            code, body, headers = reads.get("/api/snapshot", {"since": version, "wait": "20"})
            assert (code, body, headers) == (304, b"", {"ETag": f'"{version}"'})
        return clock() - start

    with ThreadPoolExecutor(2) as pool:
        tabs = [pool.submit(tab) for _ in range(2)]
        assert [f.result(timeout=30) for f in tabs] == [60, 60]
    assert source.builds == 1
    assert wake.waits == [20] * 6


def test_commit_during_wait_wakes_and_builds_inside_ttl(board) -> None:
    reads, wake, clock, source = board
    version = load(reads)

    def commit() -> None:
        wake.value += 1
        source.revision += 1

    clock.on_sleep = commit
    code, body, _ = reads.get("/api/snapshot", {"since": version, "wait": "20"})
    assert code == 200
    assert json.loads(body)["version"] != version
    assert clock() == 0.05
    assert source.builds == 2


def test_commit_between_polls_builds_without_waiting(board) -> None:
    reads, wake, clock, source = board
    version = load(reads)
    wake.value += 1
    source.revision += 1
    assert reads.get("/api/snapshot", {"since": version, "wait": "20"})[0] == 200
    assert clock() == 0
    assert wake.waits == []
    assert source.builds == 2


def test_two_tabs_share_the_build_after_a_commit(board) -> None:
    reads, wake, _, source = board
    version = load(reads)
    wake.value += 1
    source.revision += 1
    rendezvous = threading.Barrier(2)

    def tab() -> int:
        rendezvous.wait(timeout=2)
        return reads.get("/api/snapshot", {"since": version, "wait": "20"})[0]

    with ThreadPoolExecutor(2) as pool:
        tabs = [pool.submit(tab) for _ in range(2)]
        assert [f.result(timeout=30) for f in tabs] == [200, 200]
    assert source.builds == 2


def test_two_tabs_share_a_build_published_before_it_is_cached(board, monkeypatch: pytest.MonkeyPatch) -> None:
    reads, wake, _, source = board
    version = load(reads)
    wake.value += 1
    source.revision += 1
    published, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    original_build, original_snapshot, original_current = reads._build, reads.snapshot, reads._current

    def paused_build():
        value = original_build()
        published.set()
        assert release.wait(timeout=30)
        return value

    def observed_snapshot():
        value = original_snapshot()
        # On the old path, capture the stale value before releasing the build.
        second_entered.set()
        return value

    def observed_current():
        if published.is_set():
            # The second tab must now wait for the first tab's refresh lock.
            second_entered.set()
        return original_current()

    monkeypatch.setattr(reads, "_build", paused_build)
    monkeypatch.setattr(reads, "snapshot", observed_snapshot)
    monkeypatch.setattr(reads, "_current", observed_current)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(reads.get, "/api/snapshot", {"since": version, "wait": "20"})
        try:
            assert published.wait(timeout=30)
            second = pool.submit(reads.get, "/api/snapshot", {"since": version, "wait": "20"})
            assert second_entered.wait(timeout=30)
        finally:
            release.set()
        replies = [first.result(timeout=30), second.result(timeout=30)]
    new_version = json.loads(replies[0][1])["version"]
    assert new_version != version
    for code, body, headers in replies:
        assert code == 200
        assert json.loads(body)["version"] == new_version
        assert headers["ETag"] == f'"{new_version}"'
    assert source.builds == 2


def test_commit_during_build_is_seen_on_the_next_round(board, monkeypatch: pytest.MonkeyPatch) -> None:
    reads, wake, _, source = board

    def world() -> World:
        wake.value += 1
        return source.world()

    monkeypatch.setattr(reads.worlds, "world", world)
    version = load(reads)
    monkeypatch.setattr(reads.worlds, "world", source.world)
    assert reads.get("/api/snapshot", {"since": version, "wait": "20"})[0] == 304
    assert source.builds == 2
    assert wake.waits == []


def test_database_error_never_waits_and_bypasses_cache(board) -> None:
    reads, wake, _, source = board
    version = load(reads)
    source.error = "database unavailable"
    assert reads.get("/api/snapshot", {"since": version, "wait": "20"})[0] == 200
    assert wake.waits == []
    assert source.builds == 2


def test_unavailable_wake_uses_the_ordinary_path(board) -> None:
    reads, wake, _, source = board
    version = load(reads)
    wake.available = False
    assert reads.get("/api/snapshot", {"since": version, "wait": "20"})[0] == 304
    assert wake.waits == []
    assert source.builds == 1


def test_database_health_failure_during_wait_is_published(board) -> None:
    reads, _, clock, source = board
    version = load(reads)

    def unhealthy() -> None:
        source.error = "database unavailable"

    clock.on_sleep = unhealthy
    code, body, _ = reads.get("/api/snapshot", {"since": version, "wait": "20"})
    assert code == 200
    assert json.loads(body)["server"]["database_error"] == source.error
    assert source.builds == 2


@pytest.mark.parametrize("query", [{"since": "old", "wait": "20"}, {"wait": "20"},
                                  {"wait": "0"}, {"wait": "bad"}, {}])
def test_ordinary_queries_never_wait(board, query: dict[str, str]) -> None:
    reads, wake, _, _ = board
    version = load(reads)
    assert reads.get("/api/snapshot", query, f'"{version}"')[0] == (200 if query.get("since") == "old" else 304)
    assert wake.waits == []


def test_wait_is_capped_at_twenty_five_seconds(board) -> None:
    reads, wake, clock, source = board
    version = load(reads)
    assert reads.get("/api/snapshot", {"since": version, "wait": "999"})[0] == 304
    assert wake.waits == [25]
    assert clock() == 25
    assert source.builds == 1
