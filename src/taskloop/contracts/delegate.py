"""Records at the task-loop / delegate boundary (the wire is a subprocess: `route.py run` in, one JSON answer out).

Mirrors of what delegate emits; delegate's generated contract.json is the authority and a later release checks these fields
against it. `RunRequest.to_argv` is the only place that builds the `route.py run` argv."""
from dataclasses import field
from typing import Any, ClassVar, Literal

from taskloop.contracts.codec import record, table_of
from taskloop.contracts.trace import Tokens

REASON_TIMEOUT = "timeout"  # the wire id of a worker that did not finish within --timeout
REASON_OVERRUN = "overrun"  # made by the engine: a reviewer call used its budget


@record
class RunRequest:
    """One `route.py run`. The engine's limits travel as flags (`timeout_s`, `idle_s`): delegate stops the worker's tree at them."""

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
    call_id: str = ""
    timeout_s: int = 0
    idle_s: int = 0
    live_file: str = ""  # DELEGATE_LIVE_FILE: where delegate appends the worker's live events

    def to_argv(self, python: str, route: str) -> list[str]:
        out = [python, route, "run", self.role, "--brief", self.brief_path, "--cwd", self.cwd, "--schema", self.schema_path]
        if self.unattended:
            out.append("--unattended")
        out += ["--parent", self.parent, "--task", self.task, "--title", self.title[:120]]
        for flag, value in (("--resume", self.resume), ("--authored-by", self.authored_by), ("--call-id", self.call_id),
                            ("--timeout", self.timeout_s), ("--idle", self.idle_s)):
            if value:
                out += [flag, str(value)]
        return out

    def env(self) -> dict[str, str]:
        return {"DELEGATE_LIVE_FILE": self.live_file} if self.live_file else {}


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
class UsageTokens:
    """Per call, never cumulative; in_fresh is the uncached input, cache_write null when the vendor does not report it."""

    in_fresh: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    out: int | None = None
    cache_write_by_ttl: dict[str, int] | None = None


@record
class Usage:
    tokens: UsageTokens | None = None
    cost: float = 0.0
    secs: float = 0.0
    turns: int | None = None
    context_k: float | None = None
    answer_bytes: int = 0
    ref: str | None = None
    last_activity_at: str | None = None
    warm_until: str | None = None
    ttl_s: int | None = None
    ttl_source: Literal["vendor_default", "observed", "unknown"] = "unknown"
    cost_usd: float | None = None
    cost_source: Literal["harness", "unknown", "free"] = "unknown"
    accounting: Literal["exact", "estimated", "unknown"] = "unknown"


@record
class Denial:
    """One refusal in the answer; `sandbox_limit` ones are noise."""

    kind: Literal["policy", "sandbox_limit", "secret"]
    tool: str | None = None
    path: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


@record
class TranscriptInfo:
    """The transcript file and the byte window this call wrote."""

    path: str
    kind: Literal["codex", "claude", "opencode_export"]
    from_: int = field(metadata={"name": "from"})
    to: int
    bytes: int


@record
class Survivor:
    pid: int
    start: str | None = None


@record
class WorkerEnd:
    """How the worker's life ended (worker-run v1 `worker`): the delegate stopped its whole tree before it answered. `worker_survived`
    names pids that outlived SIGTERM and SIGKILL; pid, pgid and start name the process it launched."""

    end: Literal["ok", "error", "timeout", "worker_survived"] = "ok"
    stopped: bool = False
    term_sent: bool = False
    kill_sent: bool = False
    waited_s: float = 0.0
    survivors: list[Survivor] = field(default_factory=list)
    pid: int | None = None
    pgid: int | None = None
    start: str | None = None


@record
class DelegateResult:
    """The answer of `route.py run` (delegate contract 3): `stop` is None for a done call or the agent-tool handoff
    (`agent_model` set); no status, next, reason or retry_after."""

    contract: Literal[3] = 3
    stop: StopFacts | None = None
    data: dict[str, Any] | None = None
    text: str = ""
    ref: str | None = None
    lane: str | None = None
    model: str | None = None
    effort: str | None = None
    family: str | None = None
    flag: str | None = None
    cost: float = 0.0
    tokens: Tokens | None = None
    denied: list[Denial] = field(default_factory=list)
    secs: float = 0.0
    run_id: str | None = None
    call_id: str | None = None
    transcript: str | None = None
    transcript_info: TranscriptInfo | None = None
    transcript_status: str | None = None
    say: str = ""
    git_violation: list[str] = field(default_factory=list)
    usage: Usage | None = None
    context: dict[str, Any] | None = None
    worker: WorkerEnd | None = None
    exit_code: int | None = None  # the worker's exit status (negative: killed by that signal)
    first_error: str = ""
    fallback: bool | None = None
    first_lane: str | None = None
    warning: str = ""
    ask_kind: str = ""
    warnings: list[str] = field(default_factory=list)
    agent_model: str | None = None


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
    pid: int
    lane: str = ""
    model: str = ""
    effort: str = ""
    role: str = ""


@record
class LiveCmdStart(LiveRec):
    KIND: ClassVar[str] = "cmd_start"
    id: str
    text: str
    cwd: str = ""
    prov: bool = False


@record
class LiveCmdEnd(LiveRec):
    KIND: ClassVar[str] = "cmd_end"
    id: str
    exit: int | None = None  # null: the harness did not say
    secs: float = 0.0
    out: str = ""


@record
class LiveToolStart(LiveRec):
    KIND: ClassVar[str] = "tool_start"
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
    n: int = 0
    of: int = 0
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


LiveEvent = (LiveStart | LiveCmdStart | LiveCmdEnd | LiveToolStart | LiveToolEnd | LiveMsg | LiveThink | LiveTokens | LiveStall | LiveRetry
             | LiveEnd | LiveRaw)
LIVE_EVENT = table_of(LiveStart, LiveCmdStart, LiveCmdEnd, LiveToolStart, LiveToolEnd, LiveMsg, LiveThink, LiveTokens, LiveStall, LiveRetry,
                      LiveEnd, LiveRaw)
