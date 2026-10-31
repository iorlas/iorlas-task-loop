"""How a run's end reads in the trace, on its last node and in its last move; where its minutes went; the reflection as one comment line."""
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from taskloop.contracts import log as rec
from taskloop.contracts.ask import BudgetLine
from taskloop.contracts.enums import Outcome
from taskloop.contracts.kinds import ASK_NAME, ASKS, FINISH, Kind
from taskloop.contracts.stores import JsonlStore
from taskloop.domain.matchers import clip


def node_outcome(outcome: Outcome, kind: Kind) -> str:
    """What a node still open at the close came to: the run's own end."""
    if outcome in (Outcome.LANDED, Outcome.DONE):
        return outcome.value
    if kind is Kind.PAUSE_KILLED:
        return "stopped"
    if kind.name.startswith("PAUSE_") or kind is Kind.OWNER_PARK:
        return "paused"
    if kind is Kind.WAIT_ASK:
        return "waiting"
    return "failed" if outcome is Outcome.FAILED else "asks"


def close_move(kind: Kind) -> tuple[str, str]:
    """(to, cause) of the last move, when no decision point logged one: landed, an ask, a pause, a wait, a failure."""
    if kind in FINISH:
        return "close", kind.value
    if kind is Kind.PAUSE_KILLED:
        return "pause", "stopped"
    if kind.name.startswith("PAUSE_") or kind is Kind.OWNER_PARK:
        return "pause", "paused"
    if kind is Kind.WAIT_ASK:
        return "ask", "waiting"
    return ("ask", ASK_NAME[kind]) if kind in ASKS else ("close", "failed")


def run_breakdown(log_path: str | Path, open_node: Any = None, top: int = 4) -> list[BudgetLine]:
    """Where a run's minutes went, from its engine log, longest first: BudgetLine(step, minutes, rounds). Steps under a minute are
    left out; the open step counts up to now."""
    tot: dict[str, list[float]] = {}
    for it in JsonlStore(Path(log_path), rec.decode).read_from().items:
        if isinstance(it.rec, rec.StepEnd):
            t = tot.setdefault(it.rec.step, [0.0, 0])
            t[0] += it.rec.exec_seconds or 0.0
            t[1] += 1
    if open_node:
        t = tot.setdefault(open_node.step, [0.0, 0])
        t[0] += max(0.0, time.time() - open_node.t)
        t[1] += 1
    return [BudgetLine(step=k, minutes=float(v[0] // 60), rounds=int(v[1])) for k, v in sorted(tot.items(), key=lambda kv: -kv[1][0])
            if v[0] >= 60][:top]


def reflection_text(r: Mapping[str, Any] | None) -> str:
    """The reflection as one line for the bead's Reflect comment ('' when there is none)."""
    if not r:
        return ""
    bad = "; ".join(f"[{b['cause']}] {clip(b['what'], 160)} (session {b['session']})" for b in r.get("went_badly") or []) or "none"
    wasted = (" | wasted: " + clip("; ".join(r["wasted"]), 200)) if r.get("wasted") else ""
    change = (" | change: " + clip("; ".join(r["change"]), 200)) if r.get("change") else ""
    return f" reflection: badly: {clip(bad, 500)}{wasted}{change};"
