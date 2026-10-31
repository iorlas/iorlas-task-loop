"""Dashboard run headers and terminal lines, read from the existing manifests and logs."""
from typing import Literal, final

from taskloop.contracts.run import RunState
from taskloop.contracts.wire import Rec


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
