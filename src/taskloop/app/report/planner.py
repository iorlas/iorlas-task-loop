"""What the planner costs per bead: engine log calls split by their plan nodes. Reads only."""

import json
import statistics
from collections.abc import Collection
from typing import Any

from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir

from taskloop.app.report.inputs import prefix, read_jsonl

SPLIT = ("first", "again", "amend", "back", "other")


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


def _bead_calls(locator: RunLocator, bead: str, since: float, until: float) -> tuple[list[int], dict[str, int]]:
    """The input tokens of the bead's planner calls and its plan steps by class, from its engine logs within the window."""
    ins: list[int] = []
    kinds = {"full": 0, "amend": 0, "back": 0}
    for log in (b.log for b in locator.of_bead(bead) if b.log.exists()):
        records = read_jsonl(log)
        planner_ids = {rec["id"] for rec in records
                       if rec.get("kind") == "call_start" and rec.get("role") == "planner" and rec.get("id")}
        for rec in records:
            if not since <= (rec.get("t") or 0) <= until:
                continue
            if rec.get("kind") == "call_end" and rec.get("id") in planner_ids:
                ins.append(input_tokens(rec.get("tokens")))
            if rec.get("kind") == "step_start" and rec.get("step") == "plan":
                kinds[plan_class(rec)] += 1
    return ins, kinds


def planner_stats(cfg: ConfigDir, since: float, until: float, prefixes: Collection[str] = ()) -> dict[str, Any]:
    """Planner calls and input tokens per bead from engine logs, split by plan nodes:
    first plan, full plans again (a new thread from scratch), amends, check send-backs. Reads only."""
    locator = RunLocator(cfg)
    calls = {}
    for bead in sorted({run.bead for run in locator.runs() if run.bead}):
        if prefixes and prefix(bead) not in prefixes:
            continue
        ins, kinds = _bead_calls(locator, bead, since, until)
        if ins:
            calls[bead] = (ins, kinds)
    rows = []
    totals = dict.fromkeys(SPLIT, 0)
    for bead, (ins, kinds) in calls.items():
        n = len(ins)
        first = min(1, kinds["full"] or n)
        again = max(kinds["full"] - first, 0)
        other = max(n - first - again - kinds["amend"] - kinds["back"], 0)  # retries of an invalid answer, missing logs
        for k, v in zip(SPLIT, (first, again, kinds["amend"], kinds["back"], other), strict=True):
            totals[k] += v
        rows.append(
            {
                "bead": bead,
                "calls": n,
                "first": first,
                "again": again,
                "amend": kinds["amend"],
                "back": kinds["back"],
                "other": other,
                "input": sum(ins),
            }
        )
    allin = [x for ins, _ in calls.values() for x in ins]
    return {
        "calls": len(allin),
        "beads": len(rows),
        "input": sum(allin),
        "median_input": int(statistics.median(allin)) if allin else 0,
        **totals,
        "per_bead": rows,
    }


def report_planner(config: ConfigDir, since: float, until: float, prefixes: str, *, as_json: bool) -> int:
    pre = {x.strip() for x in prefixes.split(",") if x.strip()}
    p = planner_stats(config, since, until, pre)
    if as_json:
        print(json.dumps(p, indent=1, ensure_ascii=False))
    else:
        print_planner(p)
    return 0


def planner_line(p: dict[str, Any]) -> str:
    return (
        "planner: {:d} calls on {:d} beads: {:d} first plans, {:d} full plans again, {:d} amends, {:d} check send-backs, {:d} other; "
        "input {:.1f}M, median {:d}k per call"
    ).format(
        int(p["calls"]),
        int(p["beads"]),
        int(p["first"]),
        int(p["again"]),
        int(p["amend"]),
        int(p["back"]),
        int(p["other"]),
        p["input"] / 1e6,
        int(p["median_input"] // 1000),
    )


def print_planner(p: dict[str, Any]) -> None:
    print(planner_line(p))
    print(
        "  {!s:<26} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>5} {!s:>9}".format(
            "bead", "calls", "first", "again", "amend", "back", "other", "input M"
        )
    )
    for x in sorted(p["per_bead"], key=lambda x: -x["input"]):
        print(
            "  {!s:<26} {:5d} {:5d} {:5d} {:5d} {:5d} {:5d} {:9.2f}".format(
                x["bead"],
                int(x["calls"]),
                int(x["first"]),
                int(x["again"]),
                int(x["amend"]),
                int(x["back"]),
                int(x["other"]),
                x["input"] / 1e6,
            )
        )
