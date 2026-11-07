"""STOREPATH: a store is built in stores/ (real_stores) and handed down; app, cli and the dashboard take it from the bundle.

Counted per (file, class) from the imports: a call of a store class imported from where it lives, or `Class.at(...)`, outside
taskloop/stores and tlkernel (the store layer itself). The table is what is left: it may only shrink. A site that
goes away must leave the table (the test says so), a new one fails."""
import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOMES = {
    "tlkernel.docstore": {"JsonStore"},
    "tlkernel.runrows": {"RunRows"},
    "tlkernel.receiptrows": {"DbDocSet"},
    "tlkernel.looprows": {"LoopRows"},
    "tlkernel.adrs": {"AdrStore"},
    "tlkernel.askstore": {"AskStore"},
    "tlkernel.stores": {"JsonlStore", "RunLog", "EventLog", "TraceStore"},
    "tlkernel.docrows": {"RowDocs"},
    "taskloop.stores.ticketrows": {"TicketRows"},
    "taskloop.stores.runlog": {"RunLog"},
    "taskloop.adapters.locks": {"ProcessLockTable"},
}
STORE_LAYER = ("src/taskloop/stores/", "packages/kernel/src/tlkernel/")
LEFT = {  # (file, class): constructions; delete a line when the site takes its store from the bundle
    ("src/taskloop/app/launch/dash_ports.py", "AdrStore"): 1,
    ("src/taskloop/app/loop/files.py", "LoopRows"): 1,
    ("src/taskloop/app/prune/traces.py", "TraceStore"): 1,
    ("src/taskloop/app/run/context.py", "RunLog"): 1,
    ("src/taskloop/app/workers/done_memo.py", "RunRows"): 1,
    ("src/taskloop/app/pipeline/outcomes.py", "JsonlStore"): 1,
    ("src/taskloop/app/pipeline/reflect.py", "JsonlStore"): 1,
    ("src/taskloop/app/pipeline/reload.py", "RunRows"): 1,
    ("src/taskloop/cli/land.py", "RunLog"): 1,
    ("src/taskloop/cli/land_stack.py", "RunLog"): 1,
    ("src/taskloop_dash/api/writes.py", "AskStore"): 1,
    ("src/taskloop_dash/readers/world.py", "AdrStore"): 1,
    ("src/taskloop_dash/readers/world.py", "LoopRows"): 1,
}


def constructions() -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()
    for root in ("src/taskloop", "src/taskloop_dash"):
        for path in sorted((ROOT / root).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(STORE_LAYER):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            local = {(a.asname or a.name): a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module in HOMES
                     for a in n.names if a.name in HOMES[n.module]}
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                name = f.id if isinstance(f, ast.Name) else f.value.id if isinstance(f, ast.Attribute) and f.attr == "at" and isinstance(
                    f.value, ast.Name) else ""
                if name in local:
                    found[(rel, local[name])] += 1
    return found


def test_no_store_is_built_outside_stores_except_the_shrinking_table():
    found = constructions()
    grew = {k: n for k, n in found.items() if n > LEFT.get(k, 0)}
    assert not grew, f"build it in stores/real.py and take it from the bundle (real_stores(cfg).x): {sorted(grew)}"
    gone = {k: n for k, n in LEFT.items() if found.get(k, 0) < n}
    assert not gone, f"these sites got cleaner: lower or delete their lines in LEFT: {sorted(gone)}"
