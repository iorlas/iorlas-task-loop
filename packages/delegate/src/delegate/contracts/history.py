"""`history.jsonl` (one `HistoryRow` per line, `v` 2, tagged by `kind`), and `health-checkpoint.json`.

A row is a fact, appended once and never edited. The health fold (domain/health) reads `run`, `canary` and `release` rows; the rest are for
calibration and the dashboard. A line of another shape is skipped, never migrated.
"""

from dataclasses import field
from typing import ClassVar

from delegate.contracts.codec import mutable, record, table_of
from delegate.contracts.json_types import Json
from delegate.contracts.routing import BreakerPolicy

V = 2


@record
class RunRow:
    """A worker run that ended (done or not). `done` and `outcome` are the ladder's verdict (outcome None = done)."""

    KIND: ClassVar[str] = "run"
    V = V
    ts: float
    run_id: str
    role: str
    account: str
    model: str
    effort: str
    done: bool
    task: str = ""
    call_id: str | None = None
    ref: str | None = None
    outcome: str | None = None
    fingerprint: str | None = None
    say: str | None = None
    raw_answer: str | None = None
    schema_problem: str | None = None
    until: float | None = None
    warnings: list[str] | None = None
    stream_tail: Json = None
    denials: int = 0
    secs: float | None = None
    cost: float = 0
    tokens: dict[str, Json] | None = None
    cumulative: dict[str, Json] | None = None
    five_before: float | None = None
    week_before: float | None = None
    five_after: float | None = None
    week_after: float | None = None
    overlap: list[str] = field(default_factory=list)
    slots: int | None = None
    transcript: str | None = None


@record
class RefusalRow:
    """An answer given without launching a worker; kept so refusals are countable. Never a health fact."""

    KIND: ClassVar[str] = "refusal"
    V = V
    ts: float
    outcome: str
    role: str
    call_id: str | None = None
    fingerprint: str | None = None
    say: str | None = None
    until: float | None = None
    task: str = ""
    account: str | None = None
    model: str | None = None
    resume: bool = False


@record
class CanaryRow:
    """The one probe after a bench ended answered: a `done` for the pair."""

    KIND: ClassVar[str] = "canary"
    V = V
    ts: float
    run_id: str
    account: str
    model: str


@record
class GapRow:
    KIND: ClassVar[str] = "gap"
    V = V
    ts: float
    account: str
    model: str
    gap_s: float
    finished: bool


@record
class ReleaseRow:
    """`route.py report --event ok`: the owner says the account is fine, the fold forgets its limits."""

    KIND: ClassVar[str] = "release"
    V = V
    ts: float
    account: str


@record
class ReapRow:
    KIND: ClassVar[str] = "reap"
    V = V
    ts: float
    run_id: str
    account: str
    reaped: bool
    role: str | None = None
    task: str = ""
    worker_pid: int | None = None


HistoryRow = RunRow | RefusalRow | CanaryRow | GapRow | ReleaseRow | ReapRow
ROWS = table_of(RunRow, RefusalRow, CanaryRow, GapRow, ReleaseRow, ReapRow)


@mutable
class Failure:
    ts: float
    outcome: str
    say: str


@record
class HealthCheckpoint:
    """A cache of the fold up to `state.ts`, valid only for the breaker policy it was built under."""

    V = V
    policy: BreakerPolicy
    state: dict[str, Json]  # any_breaker State.to_dict(); a checkpoint of an older shape is read as absent
