"""The dashboard's wiring: a factory.db that is absent or of another schema is a 503 with its reason, and a port that is taken is a
Failed the rounds go on without."""

import json
import sqlite3
from http.client import HTTPConnection
from pathlib import Path

from taskloop.dash_composition import DashRequest, serving
from taskloop.dash_server import DashPorts, DashServer
from taskloop.git_views import GitViews
from taskloop.operations import Failed


def request(tmp_path: Path, port: int) -> DashRequest:
    return DashRequest("tl", str(tmp_path), "auto", port, tmp_path / "factory.db", tmp_path / "artifacts")


def board_answer(address: tuple[str, int]) -> tuple[int, dict[str, str]]:
    connection = HTTPConnection(*address, timeout=5)
    connection.request("GET", "/api/board")
    response = connection.getresponse()
    return response.status, json.loads(response.read())


def test_a_missing_or_incompatible_factory_db_is_a_503_with_its_reason_never_a_stale_board(tmp_path: Path) -> None:
    with serving(request(tmp_path, 0), GitViews(5)) as address:
        assert isinstance(address, tuple)
        assert board_answer(address) == (503, {"error": "refused:database"})
        with sqlite3.connect(tmp_path / "factory.db") as other:
            other.execute("PRAGMA journal_mode=WAL")
            other.execute("PRAGMA user_version=3")
        status, body = board_answer(address)
        assert status == 503 and body["error"] in {"refused:schema", "refused:database"}


def test_a_taken_port_is_a_failed_the_rounds_go_on_without_and_no_dashboard_is_left_running(tmp_path: Path) -> None:
    busy = DashServer(DashPorts(lambda: Failed("refused", "x"), lambda _id: None, tuple, "tl", tmp_path), 0)
    try:
        with serving(request(tmp_path, busy.address[1]), GitViews(5)) as address:
            assert isinstance(address, Failed) and address.reason == "dashboard_port" and str(busy.address[1]) in address.detail
    finally:
        busy.http.server_close()


def test_without_a_dash_port_nothing_is_served(tmp_path: Path) -> None:
    with serving(None, GitViews(5)) as address:
        assert address is None
