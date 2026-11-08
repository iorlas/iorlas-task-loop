"""State and sleeping go through injected ports outside implementation boundaries.

Time.time and time.monotonic are deferred: too many files need a larger migration.
Subprocess is deferred, covered in part by .importlinter, ruff TID251 and
tests/rules/test_subprocess_rule.py.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RULE = "Take state and time through an injected narrow port; adapters implement ports."
KERNEL_DB = {
    f"packages/kernel/src/tlkernel/{name}.py" for name in (
        "beadrows", "checkpointrows", "dbparts", "diskrows", "docrows", "factorydb",
        "factorymigrate", "factoryparts", "factoryprune", "receipts", "runfacts", "storeapi", "waitrows",
    )
}
KNOWN = {
    ("sqlite3", "src/taskloop/app/loop/files.py"): "DB errors handled directly in loop code",
    ("sqlite3", "src/taskloop/app/workers/asked.py"): "Transaction connection leaked into a Protocol",
    ("sqlite3", "src/taskloop/app/workers/done_memo.py"): "Transactional memo writer uses raw connections",
    ("sqlite3", "src/taskloop/hook/prepush.py"): "Standalone hook reads the registry directly",
    ("sqlite3", "packages/dash/src/tldash/index/beadpass.py"): "DB ingestion uses raw connections",
    ("sqlite3", "packages/dash/src/tldash/readers/runprojection.py"): "DB health and read projection handle SQLite errors",
    ("sqlite3", "packages/dash/src/tldash/readers/wake.py"): "Commit watcher holds a raw connection",
    ("sqlite3", "packages/pipeline/src/tlpipeline/checkpoints.py"): "Fenced checkpoint writer uses raw connections",
    ("sqlite3", "packages/pipeline/src/tlpipeline/store_ports.py"): "Connection type leaked into a port",
    ("sleep", "packages/dash/src/tldash/cli/dash.py"): "CLI polling sleeps directly between probes",
    ("sleep", "packages/dash/src/tldash/serve.py"): "Idle watchdog sleeps directly between checks",
}


def violations(source: str) -> list[tuple[str, int]]:
    """Find SQLite imports and calls to imported time.sleep, including aliases."""
    tree = ast.parse(source)
    times = {"time"}
    sleeps: set[str] = set()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    found.append(("sqlite3", node.lineno))
                if alias.name == "time":
                    times.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "sqlite3":
                found.append(("sqlite3", node.lineno))
            if node.module == "time":
                sleeps.update(alias.asname or alias.name for alias in node.names if alias.name == "sleep")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id in sleeps) or (
            isinstance(fn, ast.Attribute) and fn.attr == "sleep"
            and isinstance(fn.value, ast.Name) and fn.value.id in times
        ):
            found.append(("sleep", node.lineno))
    return sorted(found, key=lambda item: item[1])


def outside_boundaries(source: str, path: str) -> list[tuple[str, int]]:
    """Apply offence-specific implementation boundaries to a repository path."""
    if "adapters" in Path(path).parts or path.startswith(("src/taskloop/stores/", "packages/testkit/")):
        return []
    return [(kind, line) for kind, line in violations(source) if kind != "sqlite3" or path not in KERNEL_DB]


def test_ports_only():
    found: dict[tuple[str, str], list[int]] = {}
    for top in [ROOT / "src", *sorted((ROOT / "packages").glob("*/src"))]:
        for path in sorted(top.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            for kind, line in outside_boundaries(path.read_text(encoding="utf-8"), relative):
                found.setdefault((kind, relative), []).append(line)
    new = [f"{path}:{line}: {kind}: {RULE}" for kind, path in sorted(found.keys() - KNOWN.keys())
           for line in found[kind, path]]
    stale = [f"{kind}: {path}: remove it: the table only shrinks" for kind, path in sorted(KNOWN.keys() - found.keys())]
    assert not new + stale, "\n".join(new + stale)


def test_known_reasons_describe_debt():
    for key, reason in KNOWN.items():
        assert len(reason.split()) >= 3, key


@pytest.mark.parametrize(("source", "expected"), [
    ("import sqlite3", [("sqlite3", 1)]),
    ("import sqlite3 as db", [("sqlite3", 1)]),
    ("from sqlite3 import Connection as C", [("sqlite3", 1)]),
    ("import time; time.sleep(1)", [("sleep", 1)]),
    ("import time as t; t.sleep(1)", [("sleep", 1)]),
    ("from time import sleep; sleep(1)", [("sleep", 1)]),
    ("from time import sleep as s; s(1)", [("sleep", 1)]),
    ("time.time(); time.monotonic(); other.sleep(1)", []),
    ("from other import sleep; sleep(1)", []),
    ("import other as t; t.sleep(1)", []),
    ('text = "import sqlite3" # from sqlite3 import Connection', []),
    ('"time.sleep(1)" # time.sleep(1)', []),
])
def test_scanner(source: str, expected: list[tuple[str, int]]):
    assert violations(source) == expected


@pytest.mark.parametrize(("path", "expected"), [
    ("src/taskloop/domain/planted.py", [("sqlite3", 1), ("sleep", 2)]),
    ("src/taskloop/adapters/planted.py", []),
    ("src/taskloop/stores/planted.py", []),
    ("packages/testkit/src/tltestkit/planted.py", []),
    ("packages/kernel/src/tlkernel/factorydb.py", [("sleep", 2)]),
    ("packages/kernel/src/tlkernel/domain.py", [("sqlite3", 1), ("sleep", 2)]),
    ("packages/pipeline/src/tlpipeline/planted.py", [("sqlite3", 1), ("sleep", 2)]),
])
def test_boundaries(path: str, expected: list[tuple[str, int]]):
    assert outside_boundaries("import sqlite3\ntime.sleep(1)", path) == expected
