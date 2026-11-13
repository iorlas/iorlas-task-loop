"""The dashboard's wiring: the real ports behind `dash_server` (the same read-only factory.db opening as `tl step list`, the
evidence files, the cached tracker reads and the round log), started and stopped around the rounds."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from taskloop.cli_composition import open_reads
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_model import AttemptBody, Board, FeedPage, TaskDetail, TrackerDetail
from taskloop.dash_server import DashPorts, DashServer
from taskloop.dash_task import TaskPorts, build_body, build_feed, build_task, build_tracker
from taskloop.dash_tracker import CachedTracker
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import GitViews
from taskloop.land_mode import cached_mode, known_mode
from taskloop.operations import Failed
from taskloop.round_reader import LogRow, read_round_log

STATIC = Path(__file__).parent / "dash" / "static"
LOG_LINES = 200


@dataclass(frozen=True)
class DashRequest:
    backlog: str
    tracker_root: str
    label: str
    port: int
    db: Path
    artifacts: Path
    checkout: Path


def _ports(request: DashRequest, views: GitViews) -> DashPorts:
    files = EvidenceFiles(request.artifacts)
    tracker = CachedTracker(request.label, Path(request.tracker_root), time.time)
    mode = cached_mode(known_mode(views.checkouts), request.checkout, time.monotonic)

    def board() -> Board | Failed:
        with open_reads(request.db, request.artifacts, views) as reads:
            if isinstance(reads, Failed):
                return reads
            return build_board(BoardPorts(reads, files, tracker, mode))

    def task(task_id: str) -> TaskDetail | Failed:
        with open_reads(request.db, request.artifacts, views) as reads:
            return reads if isinstance(reads, Failed) else build_task(TaskPorts(reads, files, tracker, mode), request.backlog, task_id)

    def tracker_of(task_id: str) -> TrackerDetail | Failed | None:
        return build_tracker(tracker, task_id)

    def body(task_id: str, step: str, number: int) -> AttemptBody | Failed | None:
        with open_reads(request.db, request.artifacts, views) as reads:
            if isinstance(reads, Failed):
                return reads
            return build_body(TaskPorts(reads, files, tracker), request.backlog, task_id, step, number)

    def feed(task_id: str, step: str, number: int, cursor: str | None) -> FeedPage | Failed | None:
        with open_reads(request.db, request.artifacts, views) as reads:
            if isinstance(reads, Failed):
                return reads
            return build_feed(TaskPorts(reads, files, tracker), request.backlog, task_id, step, number, cursor)

    def log() -> tuple[LogRow, ...]:
        return read_round_log(files, LOG_LINES)

    return DashPorts(board, task, tracker_of, body, log, feed, request.backlog, STATIC)


@contextmanager
def serving(request: DashRequest | None, views: GitViews) -> Generator[tuple[str, int] | Failed | None]:
    """The dashboard for the length of the block, on 127.0.0.1; nothing when `request` is None (no `--dash-port`), and a
    Failed (the block still runs, without it) when the port cannot be taken."""
    if request is None:
        yield None
        return
    try:
        server = DashServer(_ports(request, views), request.port)
    except OSError as error:
        yield Failed("unavailable", "dashboard_port", f"Port {request.port} on 127.0.0.1: {error.strerror or error}")
        return
    server.start()
    try:
        yield server.address
    finally:
        server.stop()
