"""What a run is doing right now, from its events (87 §5): eight states, one line. The server computes it from the open start/end
pairs and the last events; the page only draws it and ticks `now - since`. Pairs match by src + id. First match wins:
ended, wait, check, tool, thinking | silent, hung, engine."""

from collections.abc import Callable
from typing import Final

SILENT_AFTER = 60  # seconds without a worker line before "thinking" becomes "silent"
ENGINE_ENDS: Final = {
    "step_end": "step_start",
    "call_end": "call_start",
    "cmd_end": "cmd_start",
    "check_end": "check_start",
    "gate_end": "gate_start",
    "wait_end": "wait_start",
    "unlock": "lock",
}
WORKER_ENDS: Final = {"cmd_end": "cmd", "tool_end": "tool", "end": "start"}
Open = dict[tuple[str, str, str], dict]


def pair_key(event: dict, start_kind: str) -> tuple[str, str, str]:
    """src + the start's kind + id (a gate has none, a lock pairs by what it locks)."""
    return (event["src"], start_kind, str(event.get("id") or event.get("what") or ""))


def open_pairs(events: list[dict]) -> Open:
    """The start events that no end event has closed, oldest first."""
    out: Open = {}
    for e in events:
        ends = ENGINE_ENDS if e["src"] == "engine" else WORKER_ENDS
        starts = set(ENGINE_ENDS.values()) if e["src"] == "engine" else set(WORKER_ENDS.values())
        if e["k"] in ends:
            out.pop(pair_key(e, ends[e["k"]]), None)
        elif e["k"] in starts:
            out[pair_key(e, e["k"])] = e
    return out


def of_kind(opened: Open, *kinds: str, engine: bool | None = None) -> list[dict]:
    return [e for e in opened.values() if e["k"] in kinds and (engine is None or (e["src"] == "engine") == engine)]


def state(what: str, since: float, label: str = "", detail: str = "", **more) -> dict:
    return {"what": what, "since": since, "label": label, "detail": detail, **more}


def wait_label(e: dict) -> tuple[str, str]:
    what = str(e.get("what", "")).replace("_", " ")
    holder, until = e.get("holder") or "", e.get("until")
    return f"waiting for {what}", " · ".join(x for x in (holder, f"until {until:.0f}" if until else "") if x)


def hung_since(events: list[dict]) -> float | None:
    """When the last kill or hung vendor_error happened, if nothing started after it."""
    for e in reversed(events):
        if e["k"] == "kill" or (e["k"] == "vendor_error" and e.get("reason") == "hung"):
            return e["t"]
        if e["k"] in ("call_start", "step_start", "cmd_start"):
            return None
    return None


def worker_state(started: dict, events: list[dict], now: float) -> dict:
    last = max((e["t"] for e in events if e["src"] == started["src"]), default=started["t"])
    who = " ".join(x for x in (started.get("model"), started.get("lane")) if x)
    if now - last >= SILENT_AFTER:
        return state("silent", last, who, f"no output for {now - last:.0f}s")
    return state("thinking", last, who)


class Ctx:
    """What the rules look at: the events, their open pairs, the clock, the caller's word on the process."""

    def __init__(self, events: list[dict], now: float, alive: bool, output_t: Callable[[dict], float | None]) -> None:
        self.events, self.now, self.alive, self.output_t = events, now, alive, output_t
        self.opened = open_pairs(events)

    def last(self, *kinds: str, engine: bool) -> dict | None:
        return (of_kind(self.opened, *kinds, engine=engine)[-1:] or [None])[0]


def rule_ended(c: Ctx) -> dict | None:
    close = next((e for e in reversed(c.events) if e["k"] == "close"), None)
    if close is None and c.alive:
        return None
    return state(
        "ended", close["t"] if close else (c.events[-1]["t"] if c.events else c.now), f"ended · {close['outcome']}" if close else "ended"
    )


def rule_wait(c: Ctx) -> dict | None:
    e = c.last("wait_start", engine=True)
    return state("wait", e["t"], *wait_label(e)) if e else None


def rule_check(c: Ctx) -> dict | None:
    e = c.last("check_start", "gate_start", engine=True)
    if not e:
        return None
    label = f"{e.get('check') or 'gate'} {e.get('cmd', '')}".strip()
    return state("check", e["t"], label, f"round {e['round']}" if e.get("round") else "", last_output_t=c.output_t(e))


def rule_tool(c: Ctx) -> dict | None:
    e = c.last("cmd", "tool", engine=False)
    return state("tool", e["t"], e.get("text", "")) if e else None


def rule_worker(c: Ctx) -> dict | None:
    e = c.last("start", engine=False)
    return worker_state(e, c.events, c.now) if e else None


def rule_hung(c: Ctx) -> dict | None:
    t = hung_since(c.events)
    return state("hung", t, "worker hung, killed") if t is not None else None


def rule_engine(c: Ctx) -> dict:
    top = c.last("cmd_start", engine=True) or c.last("step_start", engine=True)
    return state("engine", top["t"] if top else c.now, (top.get("text") or top.get("step") or "") if top else "")


RULES: Final = (rule_ended, rule_wait, rule_check, rule_tool, rule_worker, rule_hung)


def state_of(events: list[dict], now: float, alive: bool, output_t: Callable[[dict], float | None] = lambda e: None) -> dict:
    """The run's state. `alive` is the caller's word on the engine process; `output_t(check_event)` the mtime of its log file."""
    c = Ctx(events, now, alive, output_t)
    return next((s for s in (rule(c) for rule in RULES) if s), None) or rule_engine(c)


def worker_of(events: list[dict]) -> dict:
    """The worker of the open (else the last) call: its lane, model, effort, harness, pid and tokens."""
    starts = [e for e in events if e["k"] == "start"]
    s = starts[-1] if starts else {}
    tokens = next((e for e in reversed(events) if e["k"] == "tokens" and (not s or e["src"] == s["src"])), None)
    return {
        "lane": s.get("lane"),
        "model": s.get("model"),
        "effort": s.get("effort"),
        "harness": s.get("harness"),
        "pid": s.get("pid"),
        "tokens": {k: tokens.get(k) for k in ("in", "cached", "out")} if tokens else None,
    }
