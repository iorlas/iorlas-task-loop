"""The dashboard's HTTP server: its endpoints, the static page whitelist and the event stream, over fake ports."""

import json
import time
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path

import pytest

from taskloop.dash_model import Board, Card, TaskDetail
from taskloop.dash_server import DashPorts, DashServer
from taskloop.operations import Failed
from taskloop.round_reader import LogRow


def card(column: str = "plan") -> Card:
    return Card("tl-1", "First", "plan" if column == "plan" else "implement", 1, None, None, None, "s1", None)


class Ports:
    """The server's reads as a fake: a board whose card moves when told, one failing task read, and a log."""

    def __init__(self, static: Path) -> None:
        self.column = "plan"
        self.rows: tuple[LogRow, ...] = (LogRow("2026-11-12T10:00:00Z", "tl", "tl-1", "plan", "admit", ("step=plan",), None),)
        self.ports = DashPorts(self.board, self.task, lambda: self.rows, "tl", static, interval=0.05)

    def board(self) -> Board | Failed:
        return Board("2026-11-12T10:00:00Z", ("s1",), (card(self.column),))

    def task(self, task_id: str) -> TaskDetail | Failed | None:
        return Failed("unavailable", "store") if task_id == "broken" else None


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[Ports, DashServer]]:
    (tmp_path / "index.html").write_text("<html>page</html>")
    (tmp_path / "secret.txt").write_text("not served")
    fake = Ports(tmp_path)
    server = DashServer(fake.ports, 0)
    server.start()
    yield fake, server
    server.stop()


def get(server: DashServer, path: str) -> tuple[int, bytes]:
    connection = HTTPConnection(*server.address, timeout=5)
    connection.request("GET", path)
    response = connection.getresponse()
    return response.status, response.read()


def test_the_endpoints_answer_json_the_page_is_served_and_nothing_else_is(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    status, body = get(server, "/api/board")
    assert status == 200 and json.loads(body)["tasks"][0]["id"] == "tl-1" and json.loads(body)["slots"] == ["s1"]
    assert json.loads(get(server, "/api/log")[1])["rows"][0]["move"] == "admit"
    assert get(server, "/") == (200, b"<html>page</html>")
    assert get(server, "/api/tasks/unknown")[0] == 404 and get(server, "/api/tasks/broken")[0] == 503
    assert get(server, "/secret.txt")[0] == 404 and get(server, "/../secret.txt")[0] == 404 and get(server, "/api/tasks/a%2F..")[0] == 404


def test_a_connected_page_is_told_of_a_moved_card_and_a_new_log_line(served: tuple[Ports, DashServer]) -> None:
    fake, server = served
    connection = HTTPConnection(*server.address, timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert response.status == 200 and response.readline() == b": open\n"
    response.readline()
    while server.hub.cards is None:  # the poller has taken its baseline: only what changes after it is sent
        time.sleep(0.01)
    fake.column = "implement"
    fake.rows += (LogRow("2026-11-12T10:01:00Z", "tl", "tl-1", "implement", "advance", ("step=implement",), None),)
    seen: list[dict[str, dict[str, str]]] = []
    while {message["kind"] for message in seen} != {"task", "log"}:  # a timeout fails the test
        line = response.readline().decode()
        if line.startswith("data: "):
            seen.append(json.loads(line[6:]))
    assert any(message["kind"] == "task" and message["task"]["column"] == "implement" for message in seen)
    connection.close()
