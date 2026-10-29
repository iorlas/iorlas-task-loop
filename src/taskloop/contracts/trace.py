"""RunTrace: one engine run as the report reads it (traces.jsonl, v2). A defaulted field is one the older rows did not carry."""
from typing import Any, ClassVar

import msgspec

from taskloop.contracts.enums import Outcome, WhyCode
from taskloop.contracts.ids import RunId
from taskloop.contracts.wire import Rec


class Tokens(Rec):
    in_: int = msgspec.field(default=0, name="in")
    cached: int = 0
    out: int = 0


class Cost(Rec):
    usd: float = 0.0


class Denied(Rec):
    tool: str
    input: dict[str, Any] = msgspec.field(default_factory=dict)


class AiCall(Rec):
    """One worker session: the engine's `session` row, `traces.sessions[]` and the delegate echo in one shape."""

    node: str
    family: str
    ref: str
    status: str
    role: str
    t: float
    transcript: str = ""
    node_id: int | None = None
    attempt: int | None = None
    run_id: str = ""
    resume: bool = False
    lane: str = ""
    model: str = ""
    effort: str = ""
    flag: str | None = None
    host: bool | None = None
    cost: float | None = None
    tokens: Tokens = msgspec.field(default_factory=Tokens)
    turns: int | None = None
    context_k: int | None = None
    denied: list[Denied] = msgspec.field(default_factory=list)
    next: str | None = None
    reason: str | None = None
    stopped: str | None = None
    prompt_chars: int | None = None
    secs: float | None = None
    warning: str | None = None


class Stats(Rec):
    writes: int = 0
    rounds: int = 0
    reviews: int = 0
    replans: int = 0
    nodes: int = 0
    tests_added: int = 0
    tests_removed: int = 0
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0


class WentBadly(Rec):
    what: str
    cause: str
    session: str
    evidence: str


class Reflection(Rec):
    went_well: list[str] = msgspec.field(default_factory=list)
    went_badly: list[WentBadly] = msgspec.field(default_factory=list)
    wasted: list[str] = msgspec.field(default_factory=list)
    change: list[str] = msgspec.field(default_factory=list)


class WriteRound(Rec):
    write: int
    round: int
    node_id: int
    ref: str
    resumed: str
    input_tokens: int
    turns: int | None = None
    prompt_chars: int | None = None
    context_k: int | None = None
    fresh: str = ""


class Verified(Rec):
    what: str
    kind: str
    verdict: str
    evidence: str
    why: str


class Fault(Rec):
    """A step that failed inside the run; `fingerprint` of a trace hashes (why_code, step, lane, exit), never prose."""

    step: str
    lane: str = ""
    exit: int | None = None
    reason: str = ""
    t: float | None = None


class RunTrace(Rec):
    V: ClassVar[int] = 2
    run: RunId
    bead: str
    repo_url: str
    worktree: str
    branch: str
    coordinator_session: str
    started: float
    ended: float
    outcome: Outcome
    why: str
    sha: str
    repo_path: str = ""
    version: str = ""
    why_code: WhyCode | None = None
    fingerprint: str = ""
    cost: Cost = msgspec.field(default_factory=Cost)
    stats: Stats = msgspec.field(default_factory=Stats)
    host: bool | None = None
    delegate_path: str = ""
    log: str = ""
    stderr: str = ""
    lanes: dict[str, Any] = msgspec.field(default_factory=dict)
    sessions: list[AiCall] = msgspec.field(default_factory=list)
    verified: list[Verified] = msgspec.field(default_factory=list)
    write_rounds: list[WriteRound] = msgspec.field(default_factory=list)
    strays: list[str] = msgspec.field(default_factory=list)
    reflection: Reflection | None = None
    lane_notes: list[str] = msgspec.field(default_factory=list)
    salvaged: bool = False
    backfilled: bool = False
    ask: str = ""
    prev_run: str = ""
    started_because: str = ""
    faults: list[Fault] = msgspec.field(default_factory=list)
    kind: str = ""  # the run's outcome.Kind value, and its fingerprint: what the storm detector counts
    kfp: str = ""
