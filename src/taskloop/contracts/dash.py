"""The dashboard's wire contract: what the page reads (GET) and sends (POST). docs/contracts/dash-api.md is its prose half.

View records, never storage: a builder in taskloop_dash/views/ fills them from the stores, the page lays them out and derives nothing
the engine decides. Times are Unix seconds; `Snapshot.t` is the server's now at build time, and the page ages from it plus the
browser time elapsed since the fetch (a 304 keeps the old `t`). Ids are bd ids as bd prints them, paired with their project
wherever a row can come from more than one. A field with no source yet keeps its default and the doc names the
slice that fills it.
"""
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, final

import msgspec

from taskloop.contracts.ids import WireBead
from taskloop.contracts.needs import NeedRow
from taskloop.contracts.pickset import QueueItem
from taskloop.contracts.wire import Rec


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


@final
class LoopInfo(Rec):
    """One repo's loop. `health` is the strip: ok (a loop runs, or nothing is ready), stalled (a loop beats, ready beads wait and nothing
    happened for LOOP_STALL_S), absent (the reconcile NoLoop finding: ready beads, no loop and no beat for LOOP_ABSENT_S)."""

    project: str
    running: bool
    last_activity: float | None = None
    health: Literal["ok", "stalled", "absent"] = "ok"
    ready: int = 0
    quiet_since: Annotated[float | None, msgspec.Meta(description="the last event of the repo: the stall is counted from it")] = None


@final
class ServerInfo(Rec):
    version: Annotated[str, msgspec.Meta(description="server code hash; a change means reload the page")]
    host: str
    loops: list[LoopInfo] = msgspec.field(default_factory=list)


@final
class Project(Rec):
    id: str
    name: str
    profile_error: str = ""


@final
class Epic(Rec):
    id: str
    project: str
    title: str
    done: int = 0
    total: int = 0


@final
class Totals(Rec):
    """Bead totals over the passes still in the run logs (7 days); `tone` is decided server-side from the per-lane usual
    (dash-spec §2.6)."""

    secs: int = 0
    tokens: Annotated[int, msgspec.Meta(description="fresh tokens: input - cached + output")] = 0
    usual: int | None = None
    usual_n: int = 0
    tone: Literal["", "watch", "bad", "grey"] = ""


@final
class PhaseDot(Rec):
    phase: Phase
    state: DotState


@final
class BeadCard(Rec):
    """One bead as the Board, the Goals tree, lane chips and the drawer header show it."""

    id: str
    project: str
    title: str
    column: Column
    marker: Marker
    status: Annotated[str, msgspec.Meta(description="one line; for a running bead its last action")]
    tone: Tone = ""
    t: Annotated[float | None, msgspec.Meta(description="when the bead entered its current state; the age")] = None
    epic: str | None = None
    slot: str | None = None
    lane: str | None = None
    review: Literal["on", "off", "sampled"] | None = None  # RunStart.review of the newest run
    loops: int = 0
    dots: list[PhaseDot] = msgspec.field(default_factory=list)
    needs: Annotated[list[str], msgspec.Meta(description="open blockers only")] = msgspec.field(default_factory=list)
    goal: bool = False
    waits_why: Annotated[str, msgspec.Meta(description="a ready bead no slot took: why it waits; only while a loop runs")] = ""
    cause: OwnerCause | None = None
    ack: bool = False
    totals: Totals = msgspec.field(default_factory=Totals)
    assumptions: int = 0
    shots: int = 0


@final
class Seg(Rec):
    label: str
    kind: SegKind
    t0: float
    t1: float


@final
class Piece(Rec):
    """A bead's stretch on one slot, for the Floor: a comeback in another slot is a new piece with `from_slot` set."""

    bead: str
    project: str
    slot: str
    n: int
    segs: list[Seg]
    from_slot: str | None = None
    to_slot: str | None = None
    landed: bool = False


@final
class Slot(Rec):
    id: str
    name: str
    lane: Annotated[str, msgspec.Meta(description="lane of the slot's current or last call")]
    state: Literal["running", "stuck", "look", "free", "idle", "held"]
    project: str | None = None
    bead: str | None = None
    t: float | None = None
    next: str | None = None
    idle_why: str = ""


@final
class AskOptionCard(Rec):
    """Picked by its 0-based index in `AskCard.options`, as /api/asks does today."""

    label: str
    consequence: str
    recommended: bool = False


@final
class ThreadMsg(Rec):
    by: Literal["owner", "helper", "agent"]
    t: float
    md: str


@final
class Similar(Rec):
    bead: str
    question: str
    answer: str
    t: float


@final
class AskCard(Rec):
    """An open ask or look, whole: the page never shows a one-liner (dash-spec §5.1)."""

    id: str
    bead: str
    project: str
    source: Literal["ask", "look"]
    question: str
    t: float
    blocking: bool = True
    why: str = ""
    tried: list[str] = msgspec.field(default_factory=list)
    options: list[AskOptionCard] = msgspec.field(default_factory=list)
    default: Annotated[str, msgspec.Meta(description="what a non-blocking ask went on with")] = ""
    owner_cause: OwnerCause = OwnerCause.UNKNOWN
    cause_by: Literal["agent", "owner"] = "agent"
    shots: Annotated[list[str], msgspec.Meta(description="artifact urls")] = msgspec.field(default_factory=list)
    thread: list[ThreadMsg] = msgspec.field(default_factory=list)
    ask_backs: int = 0
    similar: Similar | None = None
    stale: Annotated[int, msgspec.Meta(description="beads landed since the ask was made")] = 0


@final
class LedgerRow(Rec):
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


@final
class AdrRow(Rec):
    """A decision in force. `id` is the repo's own number (ADR-3); `project` says which repo, since two repos both have an ADR-1."""

    id: str
    text: str
    t: float
    project: str = ""
    reuses: int = 0
    last_used: float | None = None
    prune: bool = False


@final
class CauseCount(Rec):
    cause: OwnerCause
    now: int
    prev: int


@final
class Learning(Rec):
    """'Is the factory learning?': 8 weekly points, oldest first, the last one this week (dash-spec §7.1)."""

    weeks: list[str] = msgspec.field(default_factory=list)
    asks_per_landed: list[float] = msgspec.field(default_factory=list)
    repeat_asks: list[int] = msgspec.field(default_factory=list)
    sendbacks_per_bead: list[float] = msgspec.field(default_factory=list)
    durable_pct: list[float] = msgspec.field(default_factory=list)
    causes: list[CauseCount] = msgspec.field(default_factory=list)


@final
class LaneCard(Rec):
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
    slots: list[str] = msgspec.field(default_factory=list)
    running: list[str] = msgspec.field(default_factory=list)
    waiting: list[str] = msgspec.field(default_factory=list)
    status_t: float | None = None


@final
class Snapshot(Rec):
    """GET /api/snapshot[?since=<version>]: everything the four tabs need; 304 when `since` equals `version`.
    Trimmed server-side: pieces only inside the Floor window (8 h back, 2 h ahead), done beads only since local midnight,
    backlog capped at 200 with `backlog_more` the rest."""

    V: ClassVar[int] = 1
    version: str
    t: float
    server: ServerInfo
    projects: list[Project] = msgspec.field(default_factory=list)
    epics: list[Epic] = msgspec.field(default_factory=list)
    slots: list[Slot] = msgspec.field(default_factory=list)
    beads: list[BeadCard] = msgspec.field(default_factory=list)
    backlog_more: int = 0
    pieces: list[Piece] = msgspec.field(default_factory=list)
    asks: list[AskCard] = msgspec.field(default_factory=list)
    ledger: list[LedgerRow] = msgspec.field(default_factory=list)
    adrs: list[AdrRow] = msgspec.field(default_factory=list)
    learning: Learning = msgspec.field(default_factory=Learning)
    lanes: list[LaneCard] = msgspec.field(default_factory=list)
    queue: list[QueueItem] = msgspec.field(default_factory=list)  # the owner's queue strip, in pick order
    needs: list[NeedRow] = msgspec.field(default_factory=list)  # everything that waits on the owner without an ask; first on the phone


# ---- bead drawer: GET /api/bead?project=&id=


@final
class Msg(Rec):
    t: float
    icon: str
    who: str
    md: str
    phase: Phase | None = None


@final
class Cell(Rec):
    phase: Phase
    state: CellState
    secs: int = 0
    tokens: int = 0
    last: Annotated[str, msgspec.Meta(description="last comment of the stage, for the hover")] = ""


@final
class Resumed(Rec):
    slot: str
    branch: str
    waited_secs: int


@final
class Pass(Rec):
    n: int
    cells: list[Cell]
    end: PassEnd = ""
    end_text: str = ""
    resumed: Resumed | None = None
    messages: Annotated[list[Msg], msgspec.Meta(description="this pass only, newest first")] = msgspec.field(default_factory=list)


@final
class Artifact(Rec):
    name: str
    url: str
    kind: Literal["image", "file"]
    t: float
    pass_n: int | None = None
    phase: Phase | None = None


@final
class Subtask(Rec):
    text: str
    done: bool


@final
class CheckCount(Rec):
    """From the typed check results (Checks.run), never from log text."""

    passed: int
    failed: int
    total: int
    unverified: int = 0  # could not verify: neither passed nor failed


@final
class LiveBox(Rec):
    kind: Literal["run", "stuck", "exited"]
    phase: Phase
    pass_n: int
    t: float
    cmd: str = ""
    tokens: int = 0
    subtasks: list[Subtask] = msgspec.field(default_factory=list)
    checks: CheckCount | None = None
    why: Annotated[str, msgspec.Meta(description="stuck or exited: what happened, one line")] = ""
    silent_secs: int | None = None
    exit_code: int | None = None


@final
class BeadDetail(Rec):
    V: ClassVar[int] = 1
    t: float
    card: BeadCard
    description: str = ""
    acceptance: str = ""
    comments: list[Msg] = msgspec.field(default_factory=list)
    passes: list[Pass] = msgspec.field(default_factory=list)
    artifacts: list[Artifact] = msgspec.field(default_factory=list)
    waits_for: list[str] = msgspec.field(default_factory=list)
    unblocks: list[str] = msgspec.field(default_factory=list)
    live: LiveBox | None = None
    ask: AskCard | None = None


# ---- live tail: GET /api/live?project=&id=&since=<cursor>&wait=<secs>


@final
class TermLine(Rec):
    t: float
    text: str
    tone: Literal["", "err", "ok", "dim", "warn"] = ""


@final
class ToolCall(Rec):
    """Name and argument only until delegate types the outcome of a tool call."""

    t: float
    name: str
    arg: str = ""


@final
class LivePage(Rec):
    """Long-poll page of the running worker. `state` is the run-liveness rule (live, ended, crashed)."""

    V: ClassVar[int] = 1
    cursor: str
    state: Literal["live", "ended", "crashed"]
    lines: list[TermLine] = msgspec.field(default_factory=list)
    tools: list[ToolCall] = msgspec.field(default_factory=list)


# ---- writes: POST /api/<verb>, JSON body, one Result back


@final
class AnswerReq(Rec):
    """The page holds an answer 5 s before sending it; that hold is the undo, so the server has none."""

    project: str
    ask: str
    kind: Literal["answer", "ask_back"]
    option: int | None = None
    text: str = ""


@final
class LookReq(Rec):
    project: str
    bead: str
    verdict: Literal["good", "redo"]
    note: str = ""


@final
class StickReq(Rec):
    """Records the outcome request; the engine writes and commits an ADR or a factory change, the dashboard never runs git."""

    project: str
    ask: str
    outcome: Stick
    text: str = ""


@final
class CauseReq(Rec):
    project: str
    bead: WireBead
    cause: OwnerCause
    ask: str | None = None


@final
class AckReq(Rec):
    project: str
    bead: WireBead
    ack: bool


@final
class PruneReq(Rec):
    """Retire a decision in force: it stays in the store, marked retired, and the plan stage stops reading it."""

    project: str
    adr: str


@final
class ParkReq(Rec):
    project: str
    bead: WireBead


@final
class StopReq(Rec):
    project: str
    bead: WireBead


@final
class NoteReq(Rec):
    project: str
    bead: WireBead
    text: str


@final
class Result(Rec):
    ok: bool
    message: str = ""


WRITES: dict[str, type] = {
    "answer": AnswerReq,
    "look": LookReq,
    "stick": StickReq,
    "cause": CauseReq,
    "ack": AckReq,
    "prune": PruneReq,
    "park": ParkReq,
    "stop": StopReq,
    "note": NoteReq,
}

# every write the page can send, one type per verb: the server matches on it and a verb nobody handles is a type error
DashCommand = AnswerReq | LookReq | StickReq | CauseReq | AckReq | PruneReq | ParkReq | StopReq | NoteReq
