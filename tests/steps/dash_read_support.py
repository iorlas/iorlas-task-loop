"""The dashboard read tests' shared facts: the attempt key, the tracker fake and the status reads over one factory.db connection."""

import sqlite3

from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_model import Board, Comment, Fields, Ready
from taskloop.evidence_files import EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)
FIELDS = Fields(
    "P1", ("auto",), "task/tl-1", "taskloop", "2026-11-12T10:00:00Z", "2026-11-12T11:00:00Z", ("tl-0",), "Why", "Done when", "", ""
)


class Tracker:
    """The tracker reads as a fake: what it lists ready, the titles it knows and the one task it can show."""

    def __init__(self, ready: tuple[Ready, ...] = (), problem: str | None = None) -> None:
        self.listed, self.problem = ready, problem

    def ready(self) -> tuple[Ready, ...]:
        return self.listed

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {each: f"Title of {each}" for each in task_ids}

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        return (FIELDS, (Comment("denis", "2026-11-12T10:30:00Z", "Keep it small"),)) if task_id == "tl-1" else None

    def notice(self) -> str | None:
        return self.problem


def reads_of(con: sqlite3.Connection, now: float = 1000.0) -> StatusPorts:
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: now, lambda _key: None, lambda: "boot")


def board_of(con: sqlite3.Connection, files: EvidenceFiles, tracker: Tracker) -> Board:
    found = build_board(BoardPorts(reads_of(con), files, tracker))
    assert isinstance(found, Board)
    return found
