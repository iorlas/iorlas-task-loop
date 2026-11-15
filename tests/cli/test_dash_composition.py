"""The dashboard's wiring: a factory.db that is absent or of another schema is a 503 with its reason, and a port that is taken is a
Failed the rounds go on without."""

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from http.client import HTTPConnection
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path

import pytest
from land_bench import bench

from taskloop import dash_composition
from taskloop.dash_composition import DashRequest, serving
from taskloop.dash_model import LandDetail
from taskloop.dash_server import DashPorts, DashServer
from taskloop.git_views import GitViews
from taskloop.land_check import LandPorts
from taskloop.operations import Failed


def request(tmp_path: Path, port: int) -> DashRequest:
    return DashRequest("tl", str(tmp_path), "auto", ip_address("127.0.0.1"), port,
                       tmp_path / "factory.db", tmp_path / "artifacts", tmp_path)


def board_answer(address: tuple[str, int]) -> tuple[int, dict[str, str]]:
    connection = HTTPConnection(*address, timeout=5)
    connection.request("GET", "/api/board")
    response = connection.getresponse()
    return response.status, json.loads(response.read())


@pytest.mark.usefixtures("require_loopback")
def test_a_missing_or_incompatible_factory_db_is_a_503_with_its_reason_never_a_stale_board(tmp_path: Path) -> None:
    with serving(request(tmp_path, 0), GitViews(5)) as address:
        assert isinstance(address, tuple)
        assert board_answer(address) == (503, {"error": "refused:database"})
        with sqlite3.connect(tmp_path / "factory.db") as other:
            other.execute("PRAGMA journal_mode=WAL")
            other.execute("PRAGMA user_version=3")
        status, body = board_answer(address)
        assert status == 503 and body["error"] in {"refused:schema", "refused:database"}


@pytest.mark.usefixtures("require_loopback")
def test_a_taken_port_is_a_failed_the_rounds_go_on_without_and_no_dashboard_is_left_running(tmp_path: Path) -> None:
    nothing = Failed("refused", "x")
    ports = DashPorts(lambda: nothing, lambda _id: nothing, lambda _id: None, lambda *_: None, tuple,
                      lambda *_: None, lambda _id: nothing, "tl", tmp_path)
    busy = DashServer(ports, ip_address("127.0.0.1"), 0)
    try:
        with serving(request(tmp_path, busy.address[1]), GitViews(5)) as address:
            assert isinstance(address, Failed) and address.reason == "dashboard_port" and str(busy.address[1]) in address.detail
    finally:
        busy.http.server_close()


def test_selected_delivery_uses_the_registered_checkout_and_shared_land_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = bench(tmp_path)
    views = GitViews(5)
    opened: list[tuple[Path, Path, GitViews]] = []

    @contextmanager
    def open_land(database: Path, artifacts: Path, given: GitViews) -> Generator[LandPorts]:
        opened.append((database, artifacts, given))
        yield world.ports()

    monkeypatch.setattr(dash_composition, "open_land", open_land)
    requested = replace(request(tmp_path, 0), backlog="tasks", checkout=world.repo.path)
    try:
        ports = dash_composition._ports(requested, views)
        assert opened == []
        found = ports.delivery("tl-1")
        assert isinstance(found, LandDetail) and found.diff_files == 1
        assert any("Integrate" in action for action in found.actions)
        assert opened == [(requested.db, requested.artifacts, views)]
        assert world.repo.pushes == 0 and world.tracker == [] and world.execs() == []
    finally:
        world.con.close()


def test_without_a_dash_port_nothing_is_served(tmp_path: Path) -> None:
    with serving(None, GitViews(5)) as address:
        assert address is None


@pytest.mark.parametrize("host", ["192.0.2.4", "::"])
def test_unavailable_address_reports_the_selected_address_and_port(
    host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = replace(request(tmp_path, 8123), host=ip_address(host))

    def unavailable(_ports: DashPorts, given_host: IPv4Address | IPv6Address, given_port: int) -> DashServer:
        assert (given_host, given_port) == (selected.host, selected.port)
        raise OSError(99, "Address unavailable")

    monkeypatch.setattr(dash_composition, "DashServer", unavailable)
    with serving(selected, GitViews(5)) as result:
        assert isinstance(result, Failed) and result.reason == "dashboard_port"
        assert result.detail == f"Port 8123 on {host}: Address unavailable"


def test_selected_address_is_forwarded_and_server_stops_on_block_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    selected = replace(request(tmp_path, 0), host=ip_address("::1"))

    class Server:
        address = ("::1", 8123)

        def __init__(self, _ports: DashPorts, host: IPv4Address | IPv6Address, port: int) -> None:
            assert (host, port) == (selected.host, 0)

        def start(self) -> None:
            events.append("started")

        def stop(self) -> None:
            events.append("stopped")

    monkeypatch.setattr(dash_composition, "DashServer", Server)
    with pytest.raises(RuntimeError, match="block failed"), serving(selected, GitViews(5)) as address:
        assert address == ("::1", 8123)
        raise RuntimeError("block failed")
    assert events == ["started", "stopped"]
