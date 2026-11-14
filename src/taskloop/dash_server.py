"""The dashboard's HTTP server: JSON endpoints, one server-sent-events stream and the static page, on 127.0.0.1 only, in
threads of the rounds process. Read-only: every handler is a GET over reads that already exist (`dash_board`,
`dash_task`, `round_reader`). One poller thread, only while a page is connected, turns changes into stream messages.
This is the one module that imports the standard library's HTTP server (`.importlinter`: `no-runtime-mechanisms`)."""

import json
import queue
import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

from taskloop.dash_model import AttemptBody, Board, Card, FeedPage, TaskDetail, TrackerDetail
from taskloop.operations import Failed
from taskloop.round_log import IDENT
from taskloop.round_reader import LogRow

PAGES = {"": "index.html", "index.html": "index.html", "app.js": "app.js", "api.js": "api.js", "drawer.js": "drawer.js",
         "logs.js": "logs.js", "ui.js": "ui.js", "lines.js": "lines.js", "rail.js": "rail.js",
         "taskview.js": "taskview.js", "result.js": "result.js", "words.js": "words.js", "usage.js": "usage.js", "dash.css": "dash.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


@dataclass(frozen=True)
class DashPorts:
    """What the server reads: the board, one task, the round log's tail, and the folder of the static page. `interval`: seconds
    between polls; `ping`: seconds of silence before a keep-alive on the stream; `max_streams`, `queue_depth`: how many pages
    may listen and how many unsent messages one may hold before it is dropped (it reconnects and reloads)."""

    board: Callable[[], Board | Failed]
    task: Callable[[str], TaskDetail | Failed]
    tracker: Callable[[str], TrackerDetail | Failed | None]
    body: Callable[[str, str, int], AttemptBody | Failed | None]  # task, step, attempt number
    log: Callable[[], tuple[LogRow, ...]]
    feed: Callable[[str, str, int, str | None], FeedPage | Failed | None]  # task, step, attempt number, cursor
    backlog: str
    static: Path
    interval: float = 2.0
    ping: float = 15.0
    max_streams: int = 16
    queue_depth: int = 256


def _message(kind: str, **fields: object) -> str:
    return "data: " + json.dumps({"kind": kind, **fields}) + "\n\n"


class Channel:
    """One connected page's unsent messages; `closed` once it is dropped or has gone."""

    def __init__(self, depth: int) -> None:
        self.messages: queue.Queue[str] = queue.Queue(depth)
        self.closed = threading.Event()


class Hub:
    """The stream's subscribers and what each was last told. `poll` publishes only what changed since the last poll; the first
    subscriber takes the baseline at once, so nothing between its connection and the next poll is lost, and with nobody
    connected the baseline is forgotten. A board that cannot be read is said once (`error`), never shown stale; when it can be
    read again every page is told to reload (`resync`)."""

    def __init__(self, ports: DashPorts) -> None:
        self.ports, self.lock = ports, threading.Lock()
        self.subscribers: list[Channel] = []
        self.cards: dict[str, Card] | None = None
        self.seen: Counter[LogRow] | None = None
        self.failure: str | None = None

    def subscribe(self) -> Channel | None:
        """A channel for a new page, None when `max_streams` pages already listen."""
        with self.lock:
            if len(self.subscribers) >= self.ports.max_streams:
                return None
            channel, first = Channel(self.ports.queue_depth), not self.subscribers
            self.subscribers.append(channel)
        if first:
            self._guarded()
        return channel

    def unsubscribe(self, channel: Channel) -> None:
        channel.closed.set()
        with self.lock:
            if channel in self.subscribers:
                self.subscribers.remove(channel)

    def poll(self) -> None:
        with self.lock:
            listening = list(self.subscribers)
        if not listening:
            self.cards, self.seen, self.failure = None, None, None
            return
        for text in self._guarded():
            for channel in listening:
                try:
                    channel.messages.put_nowait(text)
                except queue.Full:
                    self.unsubscribe(channel)  # a page that cannot keep up is dropped; it reconnects and reloads

    def _guarded(self) -> list[str]:
        """The messages of one poll. Whatever a read raises is reported to the pages and the poller carries on."""
        try:
            return [*self._board(), *self._log()]
        except Exception as error:
            return self._failed(f"{type(error).__name__}: {error}")

    def _failed(self, text: str) -> list[str]:
        self.cards, self.seen = None, None
        if self.failure == text:
            return []
        self.failure = text
        return [_message("error", error=text)]

    def _board(self) -> list[str]:
        board = self.ports.board()
        if isinstance(board, Failed):
            return self._failed(board.word)
        known, recovered = self.cards, self.failure is not None
        self.cards, self.failure = {card.id: card for card in board.tasks}, None
        if recovered:
            return [_message("resync")]
        if known is None:
            return []
        changed = [_message("task", task=asdict(card)) for card in board.tasks if known.get(card.id) != card]
        return changed + [_message("gone", id=each) for each in known if each not in self.cards]

    def _log(self) -> list[str]:
        """The lines not seen before. Identical lines of one second are told apart by how often each stands in the tail."""
        rows, before, running = self.ports.log(), self.seen, Counter[LogRow]()
        self.seen = Counter(rows)
        found: list[str] = []
        for row in rows:
            running[row] += 1
            if before is not None and running[row] > before[row]:
                found.append(_message("log", row=asdict(row)))
        return found


JSON = "application/json"


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    kind: str


NOT_FOUND = Reply(404, b'{"error":"not_found"}', JSON)
FORBIDDEN = Reply(403, b'{"error":"forbidden_host"}', JSON)


def _json(found: Board | TaskDetail | TrackerDetail | AttemptBody | FeedPage | Failed | None) -> Reply:
    if isinstance(found, Failed):
        return Reply(503, json.dumps({"error": found.word}).encode(), JSON)
    return NOT_FOUND if found is None else Reply(200, json.dumps(asdict(found)).encode(), JSON)


FEED = re.compile(r"api/tasks/(?P<task>[A-Za-z0-9._:@+-]{1,128})/attempts/(?P<step>[a-z]+)/(?P<n>[0-9]{1,6})/feed")
BODY = re.compile(r"api/tasks/(?P<task>[A-Za-z0-9._:@+-]{1,128})/attempts/(?P<step>[a-z]+)/(?P<n>[0-9]{1,6})")
TRACKER = re.compile(r"api/tasks/(?P<task>[A-Za-z0-9._:@+-]{1,128})/tracker")
AFTER = re.compile(r"after=([0-9]{1,20}:[0-9]{1,20})")


def _feed(ports: DashPorts, found: re.Match[str], query: str) -> Reply:
    """The agent's lines of one attempt; the only query is `after=<cursor>`, the opaque cursor of the last answer."""
    after = AFTER.fullmatch(query)
    if query and after is None:
        return Reply(400, b'{"error":"bad_cursor"}', JSON)
    return _json(ports.feed(found["task"], found["step"], int(found["n"]), after[1] if after else None))


def _task_api(ports: DashPorts, path: str, query: str) -> Reply | None:
    """The endpoints of one task: its agent lines, its tracker part, its detail; None when the path is none of them."""
    if found := FEED.fullmatch(path):
        return _feed(ports, found, query)
    if found := BODY.fullmatch(path):
        return _json(ports.body(found["task"], found["step"], int(found["n"])))
    if found := TRACKER.fullmatch(path):
        return _json(ports.tracker(found["task"]))
    if path.startswith("api/tasks/") and IDENT.fullmatch(path[10:]):
        return _json(ports.task(path[10:]))
    return None


def respond(ports: DashPorts, path: str, query: str = "") -> Reply:
    """The answer to a GET that is not the stream: a JSON endpoint or one file of the static page."""
    if path == "api/board":
        return _json(ports.board())
    if path == "api/log":
        return Reply(200, json.dumps({"backlog": ports.backlog, "rows": [asdict(row) for row in ports.log()]}).encode(), JSON)
    if (reply := _task_api(ports, path, query)) is not None:
        return reply
    if path in PAGES and (file := ports.static / PAGES[path]).is_file():
        return Reply(200, file.read_bytes(), TYPES[file.suffix])
    return NOT_FOUND


def _handler(ports: DashPorts, hub: Hub, hosts: set[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            """Quiet: the rounds process's own output is the person's terminal."""

        def _reply(self, reply: Reply) -> None:
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.kind)
            self.send_header("Content-Length", str(len(reply.body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(reply.body)

        def do_GET(self) -> None:
            if self.headers.get("Host") not in hosts:  # a page served under another name (DNS rebinding) never reads this
                return self._reply(FORBIDDEN)
            path, _, query = self.path.partition("?")
            path = path.strip("/")
            if path == "api/events":
                return self._stream()
            try:
                reply = respond(ports, path, query)
            except Exception as error:  # a read that raises is the page's error, not a dropped connection and a traceback
                reply = Reply(500, json.dumps({"error": f"{type(error).__name__}: {error}"}).encode(), JSON)
            self._reply(reply)

        def _stream(self) -> None:
            channel = hub.subscribe()
            if channel is None:
                return self._reply(Reply(503, b'{"error":"too_many_pages"}', JSON))
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b": open\n\n")
                self.wfile.flush()
                while not channel.closed.is_set():
                    try:
                        text = channel.messages.get(timeout=ports.ping)
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
    """Serves until `stop`: the HTTP server and the poller, both daemon threads. `port` 0 picks a free one (`address`). Binding
    raises OSError when the port is taken. Only requests addressed to 127.0.0.1 or localhost on that port are answered."""

    def __init__(self, ports: DashPorts, port: int) -> None:
        self.hub, self.hosts = Hub(ports), set[str]()
        self.http = ThreadingHTTPServer(("127.0.0.1", port), _handler(ports, self.hub, self.hosts))
        self.http.daemon_threads = True
        self.hosts |= {f"127.0.0.1:{self.address[1]}", f"localhost:{self.address[1]}"}
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
