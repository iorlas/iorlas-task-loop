"""The dashboard's HTTP server: JSON endpoints, one server-sent-events stream and the static page, on 127.0.0.1 only, in
threads of the rounds process. Read-only: every handler is a GET over reads that already exist (`dash_board`,
`dash_task`, `round_reader`). One poller thread, only while a page is connected, turns changes into stream messages.
This is the one module that imports the standard library's HTTP server (`.importlinter`: `no-runtime-mechanisms`)."""

import json
import queue
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

from taskloop.dash_model import Board, Card, FeedPage, TaskDetail
from taskloop.operations import Failed
from taskloop.round_log import IDENT
from taskloop.round_reader import LogRow

PAGES = {"": "index.html", "index.html": "index.html", "app.js": "app.js", "api.js": "api.js", "drawer.js": "drawer.js",
         "logs.js": "logs.js", "ui.js": "ui.js", "dash.css": "dash.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
PING_SECONDS = 15.0


@dataclass(frozen=True)
class DashPorts:
    """What the server reads: the board, one task, the round log's tail, and the folder of the static page."""

    board: Callable[[], Board | Failed]
    task: Callable[[str], TaskDetail | Failed | None]
    log: Callable[[], tuple[LogRow, ...]]
    feed: Callable[[str, str, int, str | None], FeedPage | Failed | None]  # task, step, attempt number, cursor
    backlog: str
    static: Path
    interval: float = 2.0


def _message(kind: str, **fields: object) -> str:
    return "data: " + json.dumps({"kind": kind, **fields}) + "\n\n"


class Hub:
    """The stream's subscribers and the last board and log line each was told of. `poll` publishes only what changed since
    the last poll; with nobody connected it forgets the baseline, so a first subscriber is told nothing stale."""

    def __init__(self, ports: DashPorts) -> None:
        self.ports, self.lock = ports, threading.Lock()
        self.subscribers: list[queue.Queue[str]] = []
        self.cards: dict[str, Card] | None = None
        self.last: LogRow | None = None

    def subscribe(self) -> queue.Queue[str]:
        channel: queue.Queue[str] = queue.Queue()
        with self.lock:
            self.subscribers.append(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue[str]) -> None:
        with self.lock:
            self.subscribers.remove(channel)

    def poll(self) -> None:
        with self.lock:
            listening = list(self.subscribers)
        if not listening:
            self.cards, self.last = None, None
            return
        for text in (*self._board(), *self._log()):
            for channel in listening:
                channel.put(text)

    def _board(self) -> list[str]:
        board = self.ports.board()
        if isinstance(board, Failed):
            return []
        now = {card.id: card for card in board.tasks}
        known = self.cards
        self.cards = now
        return [] if known is None else [_message("task", task=asdict(card)) for card in board.tasks if known.get(card.id) != card]

    def _log(self) -> list[str]:
        rows = self.ports.log()
        seen, self.last = self.last, rows[-1] if rows else None
        if seen is None or seen not in rows:
            return []
        return [_message("log", row=asdict(row)) for row in rows[rows.index(seen) + 1:]]


JSON = "application/json"


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    kind: str


NOT_FOUND = Reply(404, b'{"error":"not_found"}', JSON)


def _json(found: Board | TaskDetail | FeedPage | Failed | None) -> Reply:
    if isinstance(found, Failed):
        return Reply(503, json.dumps({"error": found.word}).encode(), JSON)
    return NOT_FOUND if found is None else Reply(200, json.dumps(asdict(found)).encode(), JSON)


FEED = re.compile(r"api/tasks/(?P<task>[A-Za-z0-9._:@+-]{1,128})/attempts/(?P<step>[a-z]+)/(?P<n>[0-9]{1,6})/feed")
AFTER = re.compile(r"after=([0-9]{1,20}:[0-9]{1,20})")


def _feed(ports: DashPorts, found: re.Match[str], query: str) -> Reply:
    """The agent's lines of one attempt; the only query is `after=<cursor>`, the opaque cursor of the last answer."""
    after = AFTER.fullmatch(query)
    if query and after is None:
        return Reply(400, b'{"error":"bad_cursor"}', JSON)
    return _json(ports.feed(found["task"], found["step"], int(found["n"]), after[1] if after else None))


def respond(ports: DashPorts, path: str, query: str = "") -> Reply:
    """The answer to a GET that is not the stream: a JSON endpoint or one file of the static page."""
    if path == "api/board":
        return _json(ports.board())
    if path == "api/log":
        return Reply(200, json.dumps({"backlog": ports.backlog, "rows": [asdict(row) for row in ports.log()]}).encode(), JSON)
    if found := FEED.fullmatch(path):
        return _feed(ports, found, query)
    if path.startswith("api/tasks/") and IDENT.fullmatch(path[10:]):
        return _json(ports.task(path[10:]))
    if path in PAGES and (file := ports.static / PAGES[path]).is_file():
        return Reply(200, file.read_bytes(), TYPES[file.suffix])
    return NOT_FOUND


def _handler(ports: DashPorts, hub: Hub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            """Quiet: the rounds process's own output is the person's terminal."""

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            path = path.strip("/")
            if path == "api/events":
                return self._stream()
            reply = respond(ports, path, query)
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.kind)
            self.send_header("Content-Length", str(len(reply.body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(reply.body)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            channel = hub.subscribe()
            try:
                self.wfile.write(b": open\n\n")
                self.wfile.flush()
                while True:
                    try:
                        text = channel.get(timeout=PING_SECONDS)
                    except queue.Empty:
                        text = ": ping\n\n"
                    self.wfile.write(text.encode())
                    self.wfile.flush()
            except OSError:
                pass  # the page went away
            finally:
                hub.unsubscribe(channel)

    return Handler


class DashServer:
    """Serves until `stop`: the HTTP server and the poller, both daemon threads. `port` 0 picks a free one (`address`)."""

    def __init__(self, ports: DashPorts, port: int) -> None:
        self.hub = Hub(ports)
        self.http = ThreadingHTTPServer(("127.0.0.1", port), _handler(ports, self.hub))
        self.http.daemon_threads = True
        self.ports, self.done = ports, threading.Event()
        self.threads = [threading.Thread(target=self.http.serve_forever, daemon=True), threading.Thread(target=self._poll, daemon=True)]

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.http.server_address[:2]
        return str(host), port

    def _poll(self) -> None:
        while not self.done.wait(self.ports.interval):
            self.hub.poll()

    def start(self) -> None:
        for each in self.threads:
            each.start()

    def stop(self) -> None:
        self.done.set()
        self.http.shutdown()
        self.http.server_close()
        for each in self.threads:
            each.join(timeout=5)
