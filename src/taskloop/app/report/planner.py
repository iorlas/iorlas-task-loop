"""What the planner costs per bead: delegate's history rows split by the engine logs' plan nodes. Reads only."""
import os
import statistics
from collections.abc import Collection
from pathlib import Path
from typing import Any

from taskloop.adapters import ident
from taskloop.app.report.inputs import prefix, read_jsonl
from taskloop.domain.report import matchers

HISTORY = "~/.claude/plugins/data/iorlas-delegate-iorlas-marketplace/history.jsonl"


def plan_class(rec: dict[str, Any]) -> str:
    """full | amend | back for an engine log's plan step_start record, by its text."""
    t = rec.get("text") or ""
    if t == "plan: amend":
        return "amend"
    return "back" if t in ("plan: rewrite checks", "plan: plan to meet it") else "full"  # 'plan: plan', 'plan: re-plan'


def input_tokens(tk: dict[str, Any] | None) -> int:
    """All input tokens of one delegate row. delegate 0.22.0+ writes `in` with cache reads and writes already in it (Codex
    always did); older rows had uncached-only `in`, so cached rides on top: in >= cached means it is already counted."""
    i, c = int((tk or {}).get("in") or 0), int((tk or {}).get("cached") or 0)
    return i if i >= c else i + c


def planner_stats(since: float, until: float, prefixes: Collection[str] = (), history: str | Path | None = None,
                  engine_dir: str | Path | None = None) -> dict[str, Any]:
    """Planner calls per bead from delegate's history (input: `in`, plus cached on rows from before delegate 0.22), split by the engine
    logs' plan nodes:
    first plan, full plans again (a new thread from scratch), amends, check send-backs. Reads only."""
    history = Path(history or os.path.expanduser(HISTORY))
    engine_dir = Path(engine_dir or ident.config_dir() / "engine")
    calls = {}
    for r in read_jsonl(history):
        t = r.get("ts") or 0
        task = r.get("task") or ""
        if r.get("role") != "planner" or not (since <= t <= until) or not task:
            continue
        if prefixes and prefix(task) not in prefixes:
            continue
        tk = r.get("tokens") or {}
        calls.setdefault(task, []).append(input_tokens(tk))
    rows = []
    for bead, ins in sorted(calls.items()):
        kinds = {"full": 0, "amend": 0, "back": 0}
        for log in engine_dir.glob(f"{bead}-*.jsonl"):
            if not (stem := matchers.split_stem(log.stem)) or stem[0] != bead:
                continue
            for rec in read_jsonl(log):
                if rec.get("kind") == "step_start" and rec.get("step") == "plan" and since <= (rec.get("t") or 0) <= until:
                    kinds[plan_class(rec)] += 1
        n = len(ins)
        first = min(1, kinds["full"] or n)
        again = max(kinds["full"] - first, 0)
        other = max(n - first - again - kinds["amend"] - kinds["back"], 0)  # retries of an invalid answer, missing logs
        rows.append({"bead": bead, "calls": n, "first": first, "again": again, "amend": kinds["amend"],
                     "back": kinds["back"], "other": other, "input": sum(ins)})
    allin = [x for ins in calls.values() for x in ins]
    return {"calls": len(allin), "beads": len(rows), "input": sum(allin),
            "median_input": int(statistics.median(allin)) if allin else 0,
            **{k: sum(x[k] for x in rows) for k in ("first", "again", "amend", "back", "other")}, "per_bead": rows}

