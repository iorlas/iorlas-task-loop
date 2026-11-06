"""The usage census: which paths of the factory fired in a window, read off what it already records. Standard library only, read only.

    python3 dev/census.py [--days 7] [--config <config dir>] [--tests <tests dir>] [--json]

Counts, over runs started in the window: for each path (hop, land-stack, look, reflect, OpenCode, the optimistic gate outside the land
lock and the gate inside it) the records of each (kind, step) that signal it in <config>/runs/*/engine.jsonl and <config>/events.jsonl;
runs by mode, and landed runs per hour by how many owners (sessions) ran in that hour (2, 3, 4); and how many test files build an
Engine. A path with no count did not
fire: that is the evidence for deleting it (docs/architecture/review-synthesis.md, R9-52).
"""
import argparse
import ast
import collections
import json
import os
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

DAY = 86400.0
LAND_STEPS = frozenset({"land:fetch", "land:gate", "land:lock-wait", "land:merge", "land:cleanup", "land:record"})  # the single land
# path -> the test of a record that signals it. A record is {kind, step, text} (text: a command line or a note).
PATHS = {
    "hop": lambda r: r["kind"] in ("reload", "reload_fallback"),
    "land-stack": lambda r: (r["kind"] in ("step_start", "step_end") and r["step"].startswith("land:") and r["step"] not in LAND_STEPS)
    or (r["kind"] == "note" and ("ahead of the merges" in r["text"] or " merged as " in r["text"])),
    "look": lambda r: r["step"].startswith("look") or r["kind"] == "look" or "owner-look" in r["text"],
    "reflect": lambda r: r["step"].startswith("reflect") or "reflect" in r["text"].split(" ")[:2],
    "opencode": lambda r: "opencode" in r["text"].lower() and r["kind"] == "cmd_start",
}


def records(config: Path, since: float) -> Iterator[tuple[str, dict[str, str]]]:
    """(run id, {kind, step, text, t}) for every engine-log record of a run started since `since`, then the events (run id "")."""
    for log in sorted(config.glob("runs/*/engine.jsonl")):
        yield from ((log.parent.name, r) for r in _read(log, since))
    if (config / "events.jsonl").is_file():
        yield from (("", r) for r in _read(config / "events.jsonl", since))


def _read(path: Path, since: float) -> Iterator[dict[str, str]]:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and float(e.get("t") or 0) >= since:
            yield {"kind": str(e.get("kind") or ""), "step": str(e.get("step") or ""), "text": str(e.get("text") or e.get("argv") or ""),
                   "t": str(e.get("t") or 0)}


def count_paths(recs: Iterable[tuple[str, dict[str, str]]]) -> dict[str, dict[str, int]]:
    """path -> {"<kind> <step>": records}; the optimistic gate split by whether the run took the land lock before the gate."""
    out: dict[str, collections.Counter[str]] = {p: collections.Counter() for p in (*PATHS, "gate-outside-lock", "gate-inside-lock")}
    locked: set[str] = set()
    for run, r in recs:
        for path, signals in PATHS.items():
            if signals(r):
                out[path][f"{r['kind']} {r['step']}".strip()] += 1
        if r["kind"] == "lock":
            locked.add(run)
        if r["kind"] == "step_start" and r["step"] == "land:gate":
            out["gate-inside-lock" if run in locked else "gate-outside-lock"]["step_start land:gate"] += 1
    return {p: dict(c) for p, c in out.items()}


def runs_table(db: Path, since: float) -> tuple[dict[str, int], dict[int, dict[str, float]]]:
    """(runs by mode, owners running in an hour (2, 3, 4, ...) -> {hours, landed per hour}), from the run table. The run record carries
    no loop id (its `loop` is empty), so the owner, one actor per session, stands for the loop; an owner runs in an hour when a run
    of it started in it."""
    if not db.is_file():
        return {}, {}
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as con:
        rows = con.execute("SELECT started, owner, outcome, mode FROM run WHERE started >= ?", (since,)).fetchall()
    modes = collections.Counter(str(mode or "") for _, _, _, mode in rows)
    hours: dict[int, tuple[set[str], int]] = {}
    for started, owner, outcome, _mode in rows:
        if owner:
            loops, landed = hours.setdefault(int(started // 3600), (set(), 0))
            loops.add(str(owner))
            hours[int(started // 3600)] = (loops, landed + (outcome == "landed"))
    by: dict[int, list[int]] = collections.defaultdict(list)
    for loops, landed in hours.values():
        by[len(loops)].append(landed)
    return dict(modes), {n: {"hours": len(v), "landed_per_hour": round(sum(v) / len(v), 2)} for n, v in sorted(by.items())}


def engine_tests(tests: Path) -> dict[str, int]:
    """Test files that build an Engine (a call of Engine or make_engine, or a subclass of an Engine case), of all test files."""
    files = built = 0
    for path in tests.rglob("test_*.py"):
        files += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        bases = {b.id for n in ast.walk(tree) if isinstance(n, ast.ClassDef) for b in n.bases if isinstance(b, ast.Name)}
        built += bool({"Engine", "make_engine"} & names or {"EngineCase", "EngineTest", "StagesTest"} & bases)
    return {"test_files": files, "build_an_engine": built}


class Census(NamedTuple):
    days: float
    paths: dict[str, dict[str, int]]
    modes: dict[str, int]
    loops: dict[int, dict[str, float]]
    engine_tests: dict[str, int]


def census(config: Path, tests: Path, days: float, now: float) -> Census:
    since = now - days * DAY
    modes, loops = runs_table(config / "factory.db", since)
    return Census(days, count_paths(records(config, since)), modes, loops, engine_tests(tests))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--config", default=os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "task-loop"))
    ap.add_argument("--tests", default=str(Path(__file__).resolve().parent.parent / "tests"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = census(Path(a.config), Path(a.tests), a.days, time.time())
    if a.json:
        print(json.dumps(out._asdict(), indent=1))
        return 0
    print(f"census of the last {a.days:g} days ({a.config})")
    for path, counts in out.paths.items():
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        print(f"  {path:20} {sum(counts.values()):6}  " + ", ".join(f"{k}={v}" for k, v in top))
    print("  runs by mode:", out.modes or "none")
    print("  owners running in the hour -> hours, landed per hour:", out.loops or "none")
    print("  tests that build an Engine:", out.engine_tests)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
