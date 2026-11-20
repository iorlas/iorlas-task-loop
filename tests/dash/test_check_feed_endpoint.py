"""The checks HTTP feed uses its own validated cursor and preserves the agent endpoint."""

import json
from pathlib import Path

import pytest

from taskloop.check_feed import CheckCursor, CheckLog, CheckState, Offset, encode
from taskloop.dash_model import FeedEvent, FeedPage
from taskloop.dash_server import DashPorts, respond
from taskloop.operations import Failed

CURSOR = encode(CheckCursor(attempt="checks", block=1, logs=(Offset(log=CheckLog(position=0, name="lint", state=CheckState.RUNNING)),)))
PAGE = FeedPage(
    (FeedEvent("check", "2026-11-15T00:00:00Z", name="lint", block=1, id="1:0:0", state="running", text="hello\n"),), CURSOR, False, True
)


def ports_of(static: Path, calls: list[tuple[str, str, int, str | None]]) -> DashPorts:
    def feed(task: str, step: str, number: int, cursor: str | None) -> FeedPage | Failed | None:
        calls.append((task, step, number, cursor))
        if task == "broken":
            return Failed("unavailable", "store", "Check records are unavailable.")
        return PAGE if task == "tl-1" and number == 1 else None

    failed = Failed("unavailable", "store", "Unavailable")
    return DashPorts(
        lambda: failed,
        lambda _task: failed,
        lambda _task: failed,
        lambda _task, _step, _number: failed,
        lambda: (),
        feed,
        lambda _task: failed,
        "tasks",
        static,
    )


def test_serialized_output_and_continuation(tmp_path: Path) -> None:
    calls: list[tuple[str, str, int, str | None]] = []
    ports = ports_of(tmp_path, calls)
    route = "api/tasks/tl-1/attempts/checks/1/feed"
    reply = respond(ports, route)
    assert reply.status == 200
    body = json.loads(reply.body)
    assert body["events"][0]["block"] == 1 and body["events"][0]["text"] == "hello\n"
    assert body["events"][0]["passed"] is None and body["cursor"] == CURSOR
    assert respond(ports, route, "after=" + body["cursor"]).status == 200
    assert calls == [("tl-1", "checks", 1, None), ("tl-1", "checks", 1, CURSOR)]


@pytest.mark.parametrize(
    "query",
    ["after=", "after=1:2", "after=!!!", "before=" + CURSOR, "after=" + CURSOR + "&after=" + CURSOR, "after=e30", "after=" + "a" * 262145],
)
def test_malformed_check_queries_are_rejected_before_reading(tmp_path: Path, query: str) -> None:
    calls: list[tuple[str, str, int, str | None]] = []
    reply = respond(ports_of(tmp_path, calls), "api/tasks/tl-1/attempts/checks/1/feed", query)
    assert reply.status == 400 and not calls


def test_unknown_attempt_store_failure_agent_cursor_and_static_page(tmp_path: Path) -> None:
    calls: list[tuple[str, str, int, str | None]] = []
    ports = ports_of(tmp_path, calls)
    assert respond(ports, "api/tasks/tl-1/attempts/checks/2/feed").status == 404
    assert respond(ports, "api/tasks/absent/attempts/checks/1/feed").status == 404
    assert respond(ports, "api/tasks/broken/attempts/checks/1/feed").status == 503
    route = "api/tasks/tl-1/attempts/implement/1/feed"
    assert respond(ports, route, "after=12:34").status == 200
    assert calls[-1] == ("tl-1", "implement", 1, "12:34")
    assert respond(ports, route, "after=" + CURSOR).status == 400
    (tmp_path / "index.html").write_text("<p>Dashboard</p>")
    reply = respond(ports, "")
    assert reply.status == 200 and reply.body == b"<p>Dashboard</p>"
