"""How a run's end reads in the trace, on its last node and in its last move; where its minutes went; the reflection as one comment line."""
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from taskloop.contracts import log as rec
from taskloop.contracts.ask import BudgetLine
from taskloop.contracts.stores import JsonlStore
from taskloop.domain import outcome as oc
from taskloop.domain.matchers import clip


def outcome_for(kind: Any, why: str) -> str:
    """The trace's `outcome` word: landed, done, failed (a fault) or blocked (an ask, a pause, a wait). kind None: the
    verify-gaps ask, read from its prefix."""
    if kind in oc.FINISH:
        return str(kind.value)
    if kind:  # a stop keeps the word `failed` in the trace (the reports count it); its `loop` field says paused
        return "failed" if oc.POLICY[kind].loop == "failed" or kind == oc.Kind.PAUSE_KILLED else "blocked"
    return "failed" if why.startswith("failed:") else "blocked"


def node_outcome(outcome: str, why: str, kind: Any = None) -> str:
    """What a node still open at the close came to: the run's own end."""
    if outcome in ("landed", "done"):
        return outcome
    if kind:
        return ("stopped" if kind == oc.Kind.PAUSE_KILLED else "paused" if kind.name.startswith("PAUSE_")
                else "waiting" if kind == oc.Kind.WAIT_ASK else "failed" if outcome == "failed" else "asks")
    if why.startswith("paused:"):
        return "paused"
    if why.startswith("waiting:"):
        return "waiting"
    if why.startswith("failed: stopped"):
        return "stopped"
    return "failed" if outcome == "failed" else "blocked"


def kind_move(kind: Any) -> tuple[str, str]:
    if kind == oc.Kind.PAUSE_KILLED:
        return "pause", "stopped"
    if kind.name.startswith("PAUSE_"):
        return "pause", "paused"
    if kind == oc.Kind.WAIT_ASK:
        return "ask", "waiting"
    return ("ask", oc.ASK_NAME[kind]) if kind in oc.ASKS else ("close", "failed")


def close_move(outcome: str, why: str, kind: Any = None) -> tuple[str, str]:
    """(to, cause) of the last move, when no decision point logged one: landed, an ask, a pause, a wait, a failure."""
    if outcome in ("landed", "done"):
        return "close", outcome
    if kind:
        return kind_move(kind)
    if why.startswith("paused:"):
        return "pause", "paused"
    if why.startswith("waiting:"):
        return "ask", "waiting"
    return "close", "stopped" if why.startswith("failed: stopped") else "failed"


def run_breakdown(log_path: str | Path, open_node: Any = None, top: int = 4) -> list[BudgetLine]:
    """Where a run's minutes went, from its engine log, longest first: BudgetLine(step, minutes, rounds). Steps under a minute are
    left out; the open step counts up to now."""
    tot: dict[str, list[float]] = {}
    for it in JsonlStore(Path(log_path), rec.decode).read_from().items:
        if isinstance(it.rec, rec.StepEnd):
            t = tot.setdefault(it.rec.step, [0.0, 0])
            t[0] += it.rec.secs
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
