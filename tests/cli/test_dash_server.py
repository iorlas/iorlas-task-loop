"""The dashboard's HTTP server over fake ports: endpoints, the page whitelist, the host check, the event stream and what it does
when a read fails, a page goes away or too many connect."""

import json
import time
from collections.abc import Iterator
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path

import pytest

from taskloop.dash_model import Board, Card, FeedEvent, FeedPage, Fields, TaskDetail, TrackerDetail
from taskloop.dash_server import DashPorts, DashServer, Hub
from taskloop.operations import Failed
from taskloop.round_reader import LogRow

AT = "2026-11-12T10:00:00Z"
FIELDS = Fields("P1", (), None, None, AT, AT, (), "Why", "", "", "")


def card(task_id: str = "tl-1", column: str = "plan", title: str = "First") -> Card:
    return Card(task_id, title, "plan" if column == "plan" else "implement", 1, None, None, None, "s1", None)


def row(move: str = "admit") -> LogRow:
    return LogRow(AT, "tl", "tl-1", "plan", move, ("step=plan",), None)


class Ports:
    """The server's reads as a fake: a board of cards that can be moved, made unreadable or made to raise, one failing task read
    and a log."""

    def __init__(self, static: Path, max_streams: int = 16, queue_depth: int = 256) -> None:
        self.cards, self.mode = [card()], "ok"
        self.rows: tuple[LogRow, ...] = (row(),)
        self.ports = DashPorts(self.board, self.task, self.tracker, lambda: self.rows, self.feed, "tl", static, 0.03, 0.05,
                               max_streams, queue_depth)

    def board(self) -> Board | Failed:
        if self.mode == "raise":
            raise RuntimeError("boom")
        if self.mode == "failed":
            return Failed("refused", "schema")
        return Board(AT, ("s1",), tuple(self.cards))

    def feed(self, task_id: str, step: str, number: int, cursor: str | None) -> FeedPage | Failed | None:
        """Attempt 2 of implement has one running command; the cursor says whether the page is a tail or a follow."""
        if (task_id, step, number) != ("tl-1", "implement", 2):
            return None
        line = FeedEvent("command", "2026-11-12T10:00:00Z", id="c1", state="running", cmd="ls")
        return FeedPage((line,), "7:42", replaced=False, available=True) if cursor is None else FeedPage((), cursor, False, True)

    def task(self, task_id: str) -> TaskDetail | Failed:
        return Failed("unavailable", "store") if task_id == "broken" else TaskDetail(card(task_id), ())

    def tracker(self, task_id: str) -> TrackerDetail | Failed | None:
        """The tracker's side: tl-1 is known, `broken` is unavailable, `slow` raises, anything else is not in the tracker."""
        if task_id == "slow":
            raise RuntimeError("bd timed out")
        if task_id == "broken":
            return Failed("unavailable", "tracker")
        return TrackerDetail(FIELDS, ()) if task_id == "tl-1" else None


def part(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return {str(key): each for key, each in value.items()}


class Stream:
    """One page on `/api/events`: its messages as they come."""

    def __init__(self, server: DashServer) -> None:
        self.connection = HTTPConnection(*server.address, timeout=5)
        self.connection.request("GET", "/api/events")
        self.response: HTTPResponse = self.connection.getresponse()

    def close(self) -> None:
        self.response.close()
        self.connection.close()

    def kinds(self, wanted: set[str]) -> list[dict[str, object]]:
        """Messages until each wanted kind has come (the test times out otherwise)."""
        seen: list[dict[str, object]] = []
        while not wanted <= {str(each["kind"]) for each in seen}:
            line = self.response.readline().decode()
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
        return seen


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[Ports, DashServer]]:
    (tmp_path / "index.html").write_text("<html>page</html>")
    (tmp_path / "secret.txt").write_text("not served")
    fake = Ports(tmp_path)
    server = DashServer(fake.ports, 0)
    server.start()
    yield fake, server
    server.stop()


def get(server: DashServer, path: str, host: str | None = None) -> tuple[int, bytes]:
    connection = HTTPConnection(*server.address, timeout=5)
    connection.putrequest("GET", path, skip_host=host is not None)
    if host is not None:
        connection.putheader("Host", host)
    connection.endheaders()
    response = connection.getresponse()
    return response.status, response.read()


def test_the_endpoints_answer_json_the_page_is_served_and_nothing_else_is(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    status, body = get(server, "/api/board")
    assert status == 200 and json.loads(body)["tasks"][0]["id"] == "tl-1" and json.loads(body)["slots"] == ["s1"]
    assert json.loads(get(server, "/api/log")[1])["rows"][0]["move"] == "admit"
    assert get(server, "/") == (200, b"<html>page</html>")
    assert get(server, "/api/tasks/unknown")[0] == 200 and get(server, "/api/tasks/broken")[0] == 503
    assert get(server, "/secret.txt")[0] == 404 and get(server, "/../secret.txt")[0] == 404 and get(server, "/api/tasks/a%2F..")[0] == 404


def test_only_a_request_addressed_to_the_local_server_is_answered(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    port = server.address[1]
    assert get(server, "/api/board", f"localhost:{port}")[0] == 200
    for host in ("evil.example", f"evil.example:{port}", "127.0.0.1", f"127.0.0.1:{port + 1}", "localhost.evil.example"):
        assert get(server, "/api/board", host)[0] == 403, host
        assert get(server, "/", host)[0] == 403, host
    connection = HTTPConnection(*server.address, timeout=5)
    connection.request("GET", "/api/events", headers={"Host": "evil.example"})
    assert connection.getresponse().status == 403


def test_a_title_with_markup_is_data_and_the_page_never_builds_html_from_data() -> None:
    hostile = '<img src=x onerror="alert(1)"> & "quotes"'
    assert json.loads(json.dumps({"title": hostile}))["title"] == hostile
    page = Path(__file__).resolve().parents[2] / "src/taskloop/dash/static"
    unsafe = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")
    for script in page.glob("*.js"):
        assert not any(word in script.read_text() for word in unsafe), script


def test_a_connected_page_is_told_of_a_moved_card_a_vanished_one_and_every_new_log_line(served: tuple[Ports, DashServer]) -> None:
    fake, server = served
    stream = Stream(server)
    assert stream.response.status == 200 and stream.response.readline() == b": open\n"
    fake.cards = [card(column="implement"), card("tl-2")]
    fake.rows = (row(), row(), row())  # two lines identical to the one already told of, in the same second
    seen = stream.kinds({"task", "log"})
    moved = [part(message["task"]) for message in seen if message["kind"] == "task"]
    assert [(each["id"], each["column"]) for each in moved if each["id"] == "tl-1"] == [("tl-1", "implement")]
    assert stream.kinds({"log"})[-1]["kind"] == "log"  # the second new line: both told of, though identical to an old one
    fake.cards = [card("tl-2")]
    assert stream.kinds({"gone"})[-1]["id"] == "tl-1"
    stream.close()


def test_the_first_moves_after_connecting_are_not_lost(served: tuple[Ports, DashServer]) -> None:
    fake, server = served
    fake.cards = [card()]
    stream = Stream(server)  # the baseline was taken before the first byte came back
    fake.cards = [card(column="implement")]
    assert part(stream.kinds({"task"})[-1]["task"])["column"] == "implement"
    stream.close()


@pytest.mark.parametrize("mode", ["failed", "raise"])
def test_a_board_that_cannot_be_read_is_said_once_and_the_poller_carries_on(served: tuple[Ports, DashServer], mode: str) -> None:
    fake, server = served
    stream = Stream(server)
    fake.mode = mode
    said = stream.kinds({"error"})
    assert said[-1]["error"] in {"refused:schema", "RuntimeError: boom"}
    assert get(server, "/api/board")[0] == (503 if mode == "failed" else 500)
    fake.mode = "ok"
    assert "resync" in {str(message["kind"]) for message in stream.kinds({"resync"})}
    assert server.threads[1].is_alive()
    stream.close()


def test_a_failed_board_answers_503_with_its_reason(served: tuple[Ports, DashServer]) -> None:
    fake, server = served
    fake.mode = "failed"
    status, body = get(server, "/api/board")
    assert status == 503 and json.loads(body) == {"error": "refused:schema"}


def test_a_page_that_goes_away_is_forgotten(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    stream = Stream(server)
    stream.response.readline()
    assert len(server.hub.subscribers) == 1
    stream.close()
    deadline = time.monotonic() + 5
    while server.hub.subscribers and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.hub.subscribers == []


def test_no_more_pages_than_allowed_may_listen_and_a_page_that_cannot_keep_up_is_dropped(tmp_path: Path) -> None:
    fake = Ports(tmp_path, max_streams=1, queue_depth=1)
    hub = Hub(fake.ports)
    first = hub.subscribe()
    assert first is not None and hub.subscribe() is None
    for number in range(3):  # three changes, a queue that holds one
        fake.cards = [card(title=str(number), column="implement" if number % 2 else "plan")]
        hub.poll()
    assert first.closed.is_set() and hub.subscribers == []


def test_the_feed_endpoint_answers_the_tail_then_a_follow_and_refuses_a_bad_cursor_or_attempt(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    status, body = get(server, "/api/tasks/tl-1/attempts/implement/2/feed")
    assert status == 200 and json.loads(body)["cursor"] == "7:42" and json.loads(body)["events"][0]["cmd"] == "ls"
    assert json.loads(get(server, "/api/tasks/tl-1/attempts/implement/2/feed?after=7:42")[1]) == {
        "events": [], "cursor": "7:42", "replaced": False, "available": True}
    assert get(server, "/api/tasks/tl-1/attempts/implement/2/feed?after=junk")[0] == 400
    assert get(server, "/api/tasks/tl-1/attempts/implement/9/feed")[0] == 404


def test_the_tracker_part_of_a_task_is_its_own_request_with_its_own_failures(served: tuple[Ports, DashServer]) -> None:
    _fake, server = served
    status, body = get(server, "/api/tasks/tl-1/tracker")
    assert status == 200 and json.loads(body)["fields"]["description"] == "Why" and json.loads(body)["comments"] == []
    assert get(server, "/api/tasks/unknown/tracker")[0] == 404
    assert get(server, "/api/tasks/broken/tracker")[0] == 503
    status, body = get(server, "/api/tasks/slow/tracker")
    assert status == 500 and "bd timed out" in json.loads(body)["error"]
    assert "fields" not in json.loads(get(server, "/api/tasks/tl-1")[1])
