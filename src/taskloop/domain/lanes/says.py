"""The run's `why` for a step that ended on a stop. The facts decided the kind; the reason and the wording are only text."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.delegate import REASON_ENGINE_ONLY_UNENFORCED, Denial
from taskloop.domain.lanes import pin
from taskloop.domain.lanes.denials import command_of
from taskloop.domain.lanes.policy import Stop


def stop_say(stop: Stop) -> str:
    return (f"{stop.reason} {stop.fix}").strip() or f"{stop.scope}/{stop.permanence}/{stop.retry_kind}"


@dataclass(frozen=True)
class Said:
    """What a `why` is made of: the node, the stop, the text, and the pieces some kinds add."""

    node: str
    stop: Stop
    said: str
    at: str
    fix: str
    crashes: int
    denied: Sequence[Denial]


def _paused(w: Said, what: str) -> str:
    if w.stop.reason == REASON_ENGINE_ONLY_UNENFORCED:
        return pin.unenforced_why(w.node, w.said, w.stop.fix)
    return f"paused: no {what} for {w.node}{w.at} ({w.stop.reason}: {w.said}){w.fix}"


def _denied(w: Said) -> str:
    cmds = "; ".join(f"`{command_of(d)}`" for d in w.denied)
    return f"needs a human: delegate stopped the {w.node} step ({w.stop.reason}): {w.said}{f' (refused: {cmds})' if cmds else ''}"


def _stuck(w: Said) -> str:
    code = f", exit {w.stop.exit_code}" if w.stop.exit_code is not None else ""
    return f"needs a human: the {w.node} worker stopped ({w.stop.reason}{code}) and a second try on another lane did not help: {w.said}"


WHY: Final[dict[str, Callable[[Said], str]]] = {
    "PAUSE_NETWORK": lambda w: _paused(w, "network"),
    "PAUSE_LANE": lambda w: _paused(w, "lane"),
    "PAUSE_KILLED": lambda w: f"failed: stopped (the {w.node} worker was ended by a signal: {w.said})",
    "FAULT_BAD_REQUEST": lambda w: f"failed: infrastructure: {w.stop.reason}: {w.said}{w.fix}",
    "FAULT_DENIED": _denied,
    "FAULT_CRASHED": lambda w: f"failed: delegate crashed {w.crashes} times on the {w.node} step: {w.said}",
    "ASK_STUCK": _stuck,
}


def stop_why(
    node: str,
    kind: str,
    stop: Stop,
    said: str,
    until: float = 0.0,
    crashes: int = 1,
    denied: Sequence[Denial] = (),
    now: float | None = None,
) -> str:
    """`kind`: the outcome Kind's name."""
    now = time.time() if now is None else now
    at = (" until " + time.strftime("%H:%M:%S", time.localtime(until))) if until > now else ""
    w = Said(node, stop, (said or "").strip()[:200], at, f" [{stop.fix}]" if stop.fix else "", crashes, denied)
    make = WHY.get(kind)
    return make(w) if make else f"failed: the {node} step stopped ({stop.reason}) and did not recover: {w.said}"
