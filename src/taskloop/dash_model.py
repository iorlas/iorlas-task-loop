"""The dashboard's typed read model: what the page renders (docs/design/dashboard-ui.md). Display only; nothing here
decides anything, and every fact keeps its one owner (factory.db, the tracker, the evidence files)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

type Column = Literal["waiting", "plan", "implement", "checks", "land", "held", "landed"]
type State = Literal["running", "succeeded", "failed"]
type LandState = Literal["waiting", "delivering"]


def iso(epoch: float | None) -> str | None:
    """A wall time as the page reads it: ISO 8601 UTC, to the second."""
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Repeat:
    kind: Literal["repeat", "restart_at_plan"]
    reason: str


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    column: Column
    attempt: int
    repeat: Repeat | None
    step_started_at: str | None
    last_activity_at: str | None
    slot: str | None
    hold_cause: str | None
    land: LandState | None = None  # in `land` only: `waiting` for the person to run `tl step land`, `delivering` while a land runs


@dataclass(frozen=True)
class Board:
    generated_at: str
    slots: tuple[str, ...]
    tasks: tuple[Card, ...]
    notice: str | None = None  # why part of the board is stale or missing (the tracker could not be read)


@dataclass(frozen=True)
class Fields:
    priority: str
    labels: tuple[str, ...]
    branch: str | None
    claimed_by: str | None
    created_at: str
    updated_at: str
    depends_on: tuple[str, ...]
    description: str
    acceptance: str
    design: str
    notes: str


@dataclass(frozen=True)
class Comment:
    author: str
    at: str
    text: str


@dataclass(frozen=True)
class CheckLine:
    name: str
    passed: bool
    duration_ms: int
    output: str | None  # the tail of the check's log, passed or failed; None: the log is gone or unreadable
    block: int = 1


@dataclass(frozen=True)
class Answer:
    disposition: str
    text: str


@dataclass(frozen=True)
class Outcome:
    summary: str
    answer: Answer | None
    checks: tuple[CheckLine, ...]
    output: str | None


@dataclass(frozen=True)
class FeedEvent:
    """One live line (docs/design/dashboard-ui.md, *Live event*); the fields of the other types are null."""

    type: Literal["step", "check", "command", "tool", "message", "error", "waiting"]
    at: str
    step: str | None = None
    attempt: int | None = None
    name: str | None = None
    passed: bool | None = None
    duration_ms: int | None = None
    id: str | None = None
    state: Literal["running", "finished", "unfinished"] | None = None  # unfinished: its attempt ended without a finish line
    cmd: str | None = None  # a command's text, or a tool's main argument
    text: str | None = None  # a message, an error or a wait
    waited_ms: int | None = None
    exit_code: int | None = None


@dataclass(frozen=True)
class FeedPage:
    """`GET /api/tasks/<id>/attempts/<step>/<n>/feed`: the agent's lines of one attempt and the cursor to follow them from."""

    events: tuple[FeedEvent, ...]
    cursor: str | None
    replaced: bool
    available: bool


@dataclass(frozen=True)
class AttemptDetail:
    step: str
    n: int
    state: State
    started_at: str | None
    ended_at: str | None
    summary: str
    after: Literal["repeat", "restart_at_plan"] | None
    reason: str | None
    input: str | None
    result: Outcome
    feed: tuple[FeedEvent, ...]
    feed_cursor: str | None = None  # follow the agent's lines from here (`FeedPage`); None for checks and before any line


@dataclass(frozen=True)
class TaskDetail:
    """`GET /api/tasks/<id>`: from factory.db and the evidence files only, so it never waits for the tracker."""

    task: Card
    attempts: tuple[AttemptDetail, ...]


@dataclass(frozen=True)
class TrackerDetail:
    """`GET /api/tasks/<id>/tracker`: the tracker's task and its comments (`bd` calls), loaded after the drawer is open."""

    fields: Fields
    comments: tuple[Comment, ...]


@dataclass(frozen=True)
class Ready:
    """A task the tracker lists as ready under the approval label; `since` is its creation time."""

    task_id: str
    title: str
    since: str


class DashTracker(Protocol):
    """The tracker reads the dashboard makes (bounded and cached by the adapter: each is a `bd` call). A failed read
    raises; the server turns it into an unavailable answer, never an empty one."""

    def ready(self) -> tuple[Ready, ...]: ...

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]: ...

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None: ...  # None: the tracker has no such task

    def notice(self) -> str | None: ...
