"""The dashboard's typed read model: what the page renders (docs/design/dashboard-ui.md). Display only; nothing here
decides anything, and every fact keeps its one owner (factory.db, the tracker, the evidence files)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

type Column = Literal["waiting", "plan", "implement", "checks", "land", "held", "landed"]
type State = Literal["running", "succeeded", "failed"]


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


@dataclass(frozen=True)
class Board:
    generated_at: str
    slots: tuple[str, ...]
    tasks: tuple[Card, ...]


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
    output: str | None


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
    type: Literal["step", "check"]
    at: str
    step: str | None = None
    attempt: int | None = None
    name: str | None = None
    passed: bool | None = None
    duration_ms: int | None = None


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


@dataclass(frozen=True)
class TaskDetail:
    task: Card
    fields: Fields
    comments: tuple[Comment, ...]
    attempts: tuple[AttemptDetail, ...]


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

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None: ...
