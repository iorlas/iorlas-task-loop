"""The dashboard's wire contract: what the page reads (GET) and sends (POST). docs/contracts/dash-api.md is its prose half.

View records, never storage: a builder in taskloop_dash/views/ fills them from the stores, the page lays them out and derives nothing
the engine decides. Times are Unix seconds; `Snapshot.t` is the server's now at build time, and the page ages from it plus the
browser time elapsed since the fetch (a 304 keeps the old `t`). Ids are bd ids as bd prints them, paired with their project
wherever a row can come from more than one. A field with no source yet keeps its default and the doc names the
slice that fills it.
"""
from dataclasses import field
from enum import StrEnum
from typing import ClassVar, Literal

from taskloop.contracts.codec import record


class Column(StrEnum):
    """Board column, derived from engine state (dash-spec §3); a card is never dragged."""

    BACKLOG = "backlog"
    WORKING = "working"
    QUESTIONS = "questions"
    REVIEW = "review"
    LOOK = "look"
    LANDING = "landing"
    DONE = "done"


class Marker(StrEnum):
    """The one state mark of a bead (dash-spec §2.4)."""

    RUN = "run"
    ASK = "ask"
    LOOK = "look"
    SOFT_ASK = "soft_ask"
    PARKED = "parked"
    READY = "ready"
    BLOCKED = "blocked"
    DONE = "done"
    STUCK = "stuck"
    EXITED = "exited"


class Phase(StrEnum):
    """The six phases the page draws (dash-spec calls them stages; three `Stage` records already exist).

    Engine steps map onto them: plan+replan -> plan, write -> write, checks -> test,
    review+verify -> review, look -> look, gate+land -> land; reset, close and reflect are not drawn."""

    PLAN = "plan"
    WRITE = "write"
    TEST = "test"
    REVIEW = "review"
    LOOK = "look"
    LAND = "land"


class OwnerCause(StrEnum):
    """Why an agent asked or a run stopped: one list for asks and stops (dash-spec §5.2). Not the engine's transition `Cause`."""

    REQUIREMENT = "requirement"
    DECISION = "decision"
    ENVIRONMENT = "environment"
    PROCESS = "process"
    FLAKY_TEST = "flaky_test"
    WRONG_PLAN = "wrong_plan"
    OTHER = "other"
    UNKNOWN = "unknown"


class Stick(StrEnum):
    """What an answered ask became (dash-spec §5.3)."""

    ADR = "adr"
    REF = "ref"
    FACTORY = "factory"
    FIX = "fix"
    DEMOTE = "demote"
    ONCE = "once"


Tone = Literal["", "you", "bad", "run", "watch"]
SegKind = Literal["stage", "failed", "live", "ask", "answered", "parked", "look", "stuck", "projected", "wait_slot"]
CellState = Literal["empty", "visited", "small", "skipped", "live", "failed", "you", "stuck"]
DotState = Literal["todo", "done", "live", "you", "bad"]
PassEnd = Literal["", "test_failed", "replan", "asked", "parked", "lane_out", "sent_back", "stuck", "exited", "done"]


# ---- snapshot: GET /api/snapshot


@record
class LoopInfo:
    project: str
    running: bool
    last_activity: float | None = None


@record
class ServerInfo:
    version: str = field(metadata={"doc": "server code hash; a change means reload the page"})
    host: str
    loops: list[LoopInfo] = field(default_factory=list)


@record
class Project:
    id: str
    name: str


@record
class Epic:
    id: str
    project: str
    title: str
    done: int = 0
    total: int = 0


@record
class Totals:
    """Bead totals over the passes still in the run logs (7 days); `tone` is decided server-side from the per-lane usual
    (dash-spec §2.6)."""

    secs: int = 0
    tokens: int = field(default=0, metadata={"doc": "fresh tokens: input - cached + output"})
    usual: int | None = None
    usual_n: int = 0
    tone: Literal["", "watch", "bad", "grey"] = ""


@record
class PhaseDot:
    phase: Phase
    state: DotState


@record
class BeadCard:
    """One bead as the Board, the Goals tree, lane chips and the drawer header show it."""

    id: str
    project: str
    title: str
    column: Column
    marker: Marker
    status: str = field(metadata={"doc": "one line; for a running bead its last action"})
    tone: Tone = ""
    t: float | None = field(default=None, metadata={"doc": "when the bead entered its current state; the age"})
    epic: str | None = None
    slot: str | None = None
    lane: str | None = None
    loops: int = 0
    dots: list[PhaseDot] = field(default_factory=list)
    needs: list[str] = field(
        default_factory=list, metadata={"doc": "open blockers only; a landed one is dropped, so every id is in the snapshot"}
    )
    goal: bool = False
    waits_why: str = field(default="", metadata={"doc": "a ready bead no slot took: why it waits; only while a loop runs"})
    cause: OwnerCause | None = None
    ack: bool = False
    totals: Totals = field(default_factory=Totals)
    assumptions: int = 0
    shots: int = 0


@record
class Seg:
    label: str
    kind: SegKind
    t0: float
    t1: float


@record
class Piece:
    """A bead's stretch on one slot, for the Floor: a comeback in another slot is a new piece with `from_slot` set."""

    bead: str
    project: str
    slot: str
    n: int
    segs: list[Seg]
    from_slot: str | None = None
    to_slot: str | None = None
    landed: bool = False


@record
class Slot:
    id: str
    name: str
    lane: str = field(metadata={"doc": "lane of the slot's current or last call"})
    state: Literal["running", "stuck", "look", "free", "idle", "held"]
    project: str | None = None
    bead: str | None = None
    t: float | None = None
    next: str | None = None
    idle_why: str = ""


@record
class AskOptionCard:
    """Picked by its 0-based index in `AskCard.options`, as /api/asks does today."""

    label: str
    consequence: str
    recommended: bool = False


@record
class ThreadMsg:
    by: Literal["owner", "helper", "agent"]
    t: float
    md: str


@record
class Similar:
    bead: str
    question: str
    answer: str
    t: float


@record
class AskCard:
    """An open ask or look, whole: the page never shows a one-liner (dash-spec §5.1)."""

    id: str
    bead: str
    project: str
    source: Literal["ask", "look"]
    question: str
    t: float
    blocking: bool = True
    why: str = ""
    tried: list[str] = field(default_factory=list)
    options: list[AskOptionCard] = field(default_factory=list)
    default: str = field(default="", metadata={"doc": "what a non-blocking ask went on with"})
    owner_cause: OwnerCause = OwnerCause.UNKNOWN
    cause_by: Literal["agent", "owner"] = "agent"
    shots: list[str] = field(default_factory=list, metadata={"doc": "artifact urls"})
    thread: list[ThreadMsg] = field(default_factory=list)
    ask_backs: int = 0
    similar: Similar | None = None
    stale: int = field(default=0, metadata={"doc": "beads landed since the ask was made"})


@record
class LedgerRow:
    t: float
    ask: str
    bead: str
    project: str
    question: str
    status: Literal["open", "open_soft", "answered"]
    answer: str = ""
    outcome: Stick | None = None
    outcome_ref: str = ""
    cause: OwnerCause = OwnerCause.UNKNOWN


@record
class AdrRow:
    """A decision in force. `id` is the repo's own number (ADR-3); `project` says which repo, since two repos both have an ADR-1."""

    id: str
    text: str
    t: float
    project: str = ""
    reuses: int = 0
    last_used: float | None = None
    prune: bool = False


@record
class CauseCount:
    cause: OwnerCause
    now: int
    prev: int


@record
class Learning:
    """'Is the factory learning?': 8 weekly points, oldest first, the last one this week (dash-spec §7.1)."""

    weeks: list[str] = field(default_factory=list)
    asks_per_landed: list[float] = field(default_factory=list)
    repeat_asks: list[int] = field(default_factory=list)
    sendbacks_per_bead: list[float] = field(default_factory=list)
    durable_pct: list[float] = field(default_factory=list)
    causes: list[CauseCount] = field(default_factory=list)


@record
class LaneCard:
    id: str
    name: str
    plan: str
    state: Literal["ok", "watch", "locked", "stale"]
    model: str = ""
    window_pct: float | None = None
    forecast_pct: float | None = None
    resets_at: float | None = None
    week_pct: float | None = None
    locked_until: float | None = None
    forecast: str = ""
    slots: list[str] = field(default_factory=list)
    running: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    status_t: float | None = None


@record
class Snapshot:
    """GET /api/snapshot[?since=<version>]: everything the four tabs need; 304 when `since` equals `version`.
    Trimmed server-side: pieces only inside the Floor window (8 h back, 2 h ahead), done beads only since local midnight,
    backlog capped at 200 with `backlog_more` the rest."""

    V: ClassVar[int] = 1
    version: str
    t: float
    server: ServerInfo
    projects: list[Project] = field(default_factory=list)
    epics: list[Epic] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    beads: list[BeadCard] = field(default_factory=list)
    backlog_more: int = 0
    pieces: list[Piece] = field(default_factory=list)
    asks: list[AskCard] = field(default_factory=list)
    ledger: list[LedgerRow] = field(default_factory=list)
    adrs: list[AdrRow] = field(default_factory=list)
    learning: Learning = field(default_factory=Learning)
    lanes: list[LaneCard] = field(default_factory=list)


# ---- bead drawer: GET /api/bead?project=&id=


@record
class Msg:
    t: float
    icon: str
    who: str
    md: str
    phase: Phase | None = None


@record
class Cell:
    phase: Phase
    state: CellState
    secs: int = 0
    tokens: int = 0
    last: str = field(default="", metadata={"doc": "last comment of the stage, for the hover"})


@record
class Resumed:
    slot: str
    branch: str
    waited_secs: int


@record
class Pass:
    n: int
    cells: list[Cell]
    end: PassEnd = ""
    end_text: str = ""
    resumed: Resumed | None = None
    messages: list[Msg] = field(default_factory=list, metadata={"doc": "this pass only, newest first"})


@record
class Artifact:
    name: str
    url: str
    kind: Literal["image", "file"]
    t: float
    pass_n: int | None = None
    phase: Phase | None = None


@record
class Subtask:
    text: str
    done: bool


@record
class CheckCount:
    """From the typed check results (Checks.run), never from log text."""

    passed: int
    failed: int
    total: int


@record
class LiveBox:
    kind: Literal["run", "stuck", "exited"]
    phase: Phase
    pass_n: int
    t: float
    cmd: str = ""
    tokens: int = 0
    subtasks: list[Subtask] = field(default_factory=list)
    checks: CheckCount | None = None
    why: str = field(default="", metadata={"doc": "stuck or exited: what happened, one line"})
    silent_secs: int | None = None
    exit_code: int | None = None


@record
class BeadDetail:
    V: ClassVar[int] = 1
    t: float
    card: BeadCard
    description: str = ""
    acceptance: str = ""
    comments: list[Msg] = field(default_factory=list)
    passes: list[Pass] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    waits_for: list[str] = field(default_factory=list)
    unblocks: list[str] = field(default_factory=list)
    live: LiveBox | None = None
    ask: AskCard | None = None


# ---- live tail: GET /api/live?project=&id=&since=<cursor>&wait=<secs>


@record
class TermLine:
    t: float
    text: str
    tone: Literal["", "err", "ok", "dim"] = ""


@record
class ToolCall:
    """Name and argument only until delegate types the outcome of a tool call."""

    t: float
    name: str
    arg: str = ""


@record
class LivePage:
    """Long-poll page of the running worker. `state` is the run-liveness rule (live, ended, crashed)."""

    V: ClassVar[int] = 1
    cursor: str
    state: Literal["live", "ended", "crashed"]
    lines: list[TermLine] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)


# ---- writes: POST /api/<verb>, JSON body, one Result back


@record
class AnswerReq:
    """The page holds an answer 5 s before sending it; that hold is the undo, so the server has none."""

    project: str
    ask: str
    kind: Literal["answer", "ask_back"]
    option: int | None = None
    text: str = ""


@record
class LookReq:
    project: str
    bead: str
    verdict: Literal["good", "redo"]
    note: str = ""


@record
class StickReq:
    """Records the outcome request; the engine writes and commits an ADR or a factory change, the dashboard never runs git."""

    project: str
    ask: str
    outcome: Stick
    text: str = ""


@record
class CauseReq:
    project: str
    bead: str
    cause: OwnerCause
    ask: str | None = None


@record
class AckReq:
    project: str
    bead: str
    ack: bool


@record
class PruneReq:
    """Retire a decision in force: it stays in the store, marked retired, and the plan stage stops reading it."""

    project: str
    adr: str


@record
class BeadReq:
    """Body of park and stop."""

    project: str
    bead: str


@record
class NoteReq:
    project: str
    bead: str
    text: str


@record
class Result:
    ok: bool
    message: str = ""


WRITES: dict[str, type] = {
    "answer": AnswerReq,
    "look": LookReq,
    "stick": StickReq,
    "cause": CauseReq,
    "ack": AckReq,
    "prune": PruneReq,
    "park": BeadReq,
    "stop": BeadReq,
    "note": NoteReq,
}
