"""The live tail as typed lines (contracts.dash.LivePage): an event of a run's files, decoded back into the engine's own record or the
worker's Live* record, becomes a TermLine; a worker's tool call becomes a ToolCall. A kind with nothing to say yields no line. Only what
the records type is filled: no text is parsed, and a ToolCall carries delegate's one `text` as its name until delegate types the rest."""

from collections.abc import Callable
from typing import Any, Final, Literal

from taskloop.contracts import delegate, log, wire
from taskloop.contracts.dash import LivePage, TermLine, ToolCall
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views.live_events import ENGINE

TermTone = Literal["", "err", "ok", "dim", "warn"]
STATE: Final[dict[Liveness, Literal["live", "ended", "crashed"]]] = {
    Liveness.LIVE: "live", Liveness.ENDED: "ended", Liveness.CRASHED: "crashed"}
OUT_LINES = 12  # lines of a command's output shown after its exit


def retype(event: dict[str, Any]) -> Any | None:
    """The record an event dict came from (engine_event / worker_event); None when it no longer decodes."""
    body = {k: v for k, v in event.items() if k not in ("k", "src", "seq")}
    try:
        if event["src"] == ENGINE:
            return log.decode(dict(body, kind=event["k"], v=log.LogRec.V))
        return wire.load(delegate.LiveEvent, dict(body, kind=event["k"], v=delegate.LiveRec.V))
    except ValueError:
        return None


def exit_tone(code: int | None) -> TermTone:
    return "" if code is None else "ok" if code == 0 else "err"


def out_lines(t: float, out: str) -> list[TermLine]:
    return [TermLine(t=t, text=ln, tone="dim") for ln in out.splitlines()[-OUT_LINES:] if ln.strip()]


def exited(t: float, code: int | None, secs: float, out: str) -> list[TermLine]:
    tail = "" if code is None else f" {code}"
    return [TermLine(t=t, text=f"exit{tail} ({secs:.0f}s)", tone=exit_tone(code)), *out_lines(t, out)]


def line(r: Any, text: str, tone: TermTone = "") -> list[TermLine]:
    return [TermLine(t=r.t, text=text, tone=tone)]


ENGINE_LINES: Final[dict[type, Callable[[Any], list[TermLine]]]] = {
    log.StepStart: lambda r: line(r, f"> {r.text or r.step}"),
    log.StepEnd: lambda r: line(r, f"{r.step}: {r.outcome}" + (f" ({r.detail})" if r.detail else ""), "dim"),
    log.CmdStart: lambda r: line(r, f"$ {r.text}"),
    log.CmdEnd: lambda r: exited(r.t, r.exit, r.secs, r.out),
    log.CheckStart: lambda r: line(r, f"check {r.check}: {r.cmd}"),
    log.CheckEnd: lambda r: line(r, f"check {r.status}", "warn" if r.status == "unverified" else exit_tone(r.exit)),
    log.GateStart: lambda r: line(r, f"gate: {r.cmd}"),
    log.GateEnd: lambda r: line(r, "gate done", exit_tone(r.exit)),
    log.CallStart: lambda r: line(r, f"call {r.n}: {r.role} ({r.step})", "dim"),
    log.CallEnd: lambda r: line(r, f"call {r.status} {r.lane} {r.model}".rstrip(), "dim"),
    log.VendorError: lambda r: line(r, f"vendor error {r.reason} {r.lane}".rstrip(), "err"),
    log.Kill: lambda r: line(r, f"stopped {r.what}: {r.why}", "err"),
    log.Warn: lambda r: line(r, r.text, "err"),
    log.Note: lambda r: line(r, r.text, "dim"),
    log.Close: lambda r: line(r, f"run closed: {r.outcome}"),
}
WORKER_LINES: Final[dict[type, Callable[[Any], list[TermLine]]]] = {
    delegate.LiveStart: lambda r: line(r, f"worker {r.harness} {r.lane} {r.model}".rstrip(), "dim"),
    delegate.LiveCmdStart: lambda r: line(r, f"$ {r.text}"),
    delegate.LiveCmdEnd: lambda r: exited(r.t, r.exit, r.secs, r.out),
    delegate.LiveToolStart: lambda r: line(r, f"tool {r.text}", "dim"),
    delegate.LiveMsg: lambda r: line(r, r.text),
    delegate.LiveThink: lambda r: line(r, r.text, "dim"),
    delegate.LiveStall: lambda r: line(r, f"no output for {r.secs:.0f}s", "err"),
    delegate.LiveRetry: lambda r: line(r, f"retry {r.n}/{r.of} {r.why}".rstrip(), "err"),
    delegate.LiveEnd: lambda r: line(r, f"worker {r.status}", "ok" if r.status == "done" else "err"),
}


def page(events: list[dict[str, Any]], cursor: str, state: Liveness) -> LivePage:
    lines: list[TermLine] = []
    tools: list[ToolCall] = []
    for e in events:
        r = retype(e)
        if r is None:
            continue
        table = ENGINE_LINES if e["src"] == ENGINE else WORKER_LINES
        lines += table[type(r)](r) if type(r) in table else []
        if isinstance(r, delegate.LiveToolStart):
            tools.append(ToolCall(t=r.t, name=r.text))
    return LivePage(cursor=cursor, state=STATE[state], lines=lines, tools=tools)
