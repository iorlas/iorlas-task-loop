"""Dashboard run headers and terminal lines, read from the existing manifests and logs."""
from typing import Literal, final

from tlkernel.run import RunState
from tlkernel.wire import Rec


class RunHeader(Rec):
    run: str
    project: str
    mode: str
    owner: str
    session: str
    state: RunState
    started: float
    ended: float | None = None
    reason: str = ""
    bead: str = ""
    branch: str = ""
    retry_at: float = 0.0


@final
class ResourceLease(Rec):
    name: str
    holder: str
    since: float
    run: str = ""
    project: str = ""


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
