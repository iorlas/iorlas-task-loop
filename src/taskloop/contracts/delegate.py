"""Records at the task-loop / delegate boundary (the wire is a subprocess: `route.py run` in, one JSON answer out).

Mirrors of what delegate emits; delegate's generated contract.json is the authority and a later release checks these fields
against it. `RunRequest.to_argv` is the only place that builds the `route.py run` argv."""
from dataclasses import field
from typing import Any, ClassVar, Literal

from taskloop.contracts.codec import record, table_of
from taskloop.contracts.trace import Denied, Tokens


@record
class RunRequest:
    role: str
    brief_path: str
    cwd: str
    schema_path: str
    unattended: bool = True
    parent: str = ""
    task: str = ""
    title: str = ""
    resume: str = ""
    authored_by: str = ""
    host: bool = False
    call_id: str = ""
    readable_outside: list[str] = field(default_factory=list)

    def to_argv(self, python: str, route: str) -> list[str]:
        out = [python, route, "run", self.role, "--brief", self.brief_path, "--cwd", self.cwd, "--schema", self.schema_path]
        if self.unattended:
            out.append("--unattended")
        out += ["--parent", self.parent, "--task", self.task, "--title", self.title[:120]]
        for flag, value in (("--resume", self.resume), ("--authored-by", self.authored_by), ("--call-id", self.call_id)):
            if value:
                out += [flag, value]
        if self.host:
            out.append("--host")
        return out


@record
class Retry:
    kind: Literal["none", "predicted", "poll"]
    at: float | None = None


@record
class StopFacts:
    reason: str
    scope: Literal["bead", "caller", "machine", "lane", "model"]
    permanence: Literal["transient", "needs_owner"]
    retry: Retry
    ref: str = ""
    fix: str = ""
    resumable: bool = False
    partial: bool = False


@record
class Usage:
    tokens: Tokens | None = None
    cost: float = 0.0
    secs: float = 0.0
    turns: int | None = None
    context_k: float | None = None
    ref: str | None = None


@record
class DelegateResult:
    """The answer of `route.py run` (worker-run wire v3)."""

    V: ClassVar[int] = 3
    status: Literal["done", "agent", "stop", "lane_out", "error", "failed", "timeout"]
    reason: str | None = None
    next: Literal["retry", "owner", "fail"] | None = None
    data: dict[str, Any] | None = None
    text: str = ""
    ref: str | None = None
    lane: str = ""
    model: str = ""
    effort: str = ""
    family: str = ""
    flag: str | None = None
    cost: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)
    denied: list[Denied] = field(default_factory=list)
    secs: float = 0.0
    run_id: str | None = None
    call_id: str | None = None
    transcript: str | None = None
    transcript_status: str = ""
    retry_after: float | None = None
    say: str = ""
    git_violation: list[str] = field(default_factory=list)
    stop: StopFacts | None = None
    usage: Usage | None = None
    fallback: str | None = None
    first_lane: str | None = None
    rung: int | None = None
    warnings: list[str] = field(default_factory=list)
    needs_input: bool = False
    ask_user: str = ""


@record
class DelegateContract:
    worker_run: int
    features: frozenset[str] = frozenset()
    reasons: list[str] = field(default_factory=list)
    lanes: list[str] = field(default_factory=list)


@record
class WorkerStarted:
    """The first line of a live file: the worker's process ids."""

    V: ClassVar[int] = 1
    pid: int
    pgid: int
    run_id: str


@record
class LiveRec:
    V: ClassVar[int] = 1
    t: float


@record
class LiveStart(LiveRec):
    KIND: ClassVar[str] = "start"
    harness: str
    lane: str
    model: str
    effort: str
    role: str
    pid: int


@record
class LiveCmd(LiveRec):
    KIND: ClassVar[str] = "cmd"
    id: str
    text: str
    cwd: str = ""
    prov: bool = False


@record
class LiveCmdEnd(LiveRec):
    KIND: ClassVar[str] = "cmd_end"
    id: str
    exit: int | None = None
    secs: float = 0.0
    out: str = ""


@record
class LiveTool(LiveRec):
    KIND: ClassVar[str] = "tool"
    id: str
    text: str
    prov: bool = False


@record
class LiveToolEnd(LiveRec):
    KIND: ClassVar[str] = "tool_end"
    id: str
    secs: float = 0.0
    out: str = ""


@record
class LiveMsg(LiveRec):
    KIND: ClassVar[str] = "msg"
    text: str


@record
class LiveThink(LiveRec):
    KIND: ClassVar[str] = "think"
    text: str


@record
class LiveTokens(LiveRec):
    KIND: ClassVar[str] = "tokens"
    in_: int = field(default=0, metadata={"name": "in"})
    cached: int = 0
    out: int = 0


@record
class LiveStall(LiveRec):
    KIND: ClassVar[str] = "stall"
    secs: float


@record
class LiveRetry(LiveRec):
    KIND: ClassVar[str] = "retry"
    n: int
    of: int
    why: str = ""


@record
class LiveEnd(LiveRec):
    KIND: ClassVar[str] = "end"
    status: Literal["done", "timeout", "killed", "error"]
    secs: float = 0.0
    cost_usd: float = 0.0


@record
class LiveRaw(LiveRec):
    KIND: ClassVar[str] = "raw"
    type: str


LiveEvent = (LiveStart | LiveCmd | LiveCmdEnd | LiveTool | LiveToolEnd | LiveMsg | LiveThink | LiveTokens | LiveStall | LiveRetry
             | LiveEnd | LiveRaw)
LIVE_EVENT = table_of(LiveStart, LiveCmd, LiveCmdEnd, LiveTool, LiveToolEnd, LiveMsg, LiveThink, LiveTokens, LiveStall, LiveRetry,
                      LiveEnd, LiveRaw)
