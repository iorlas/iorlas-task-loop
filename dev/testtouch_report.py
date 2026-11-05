"""Layer table from dev/testtouch.py + dev/testtimes.py output: what the tests touch, how many, how much CPU.

`python3 dev/testtouch_report.py <dir>` where <dir> holds <name>.touch.json and <name>.times.json per test directory.
Layer of a test, first match: e2e (tests/e2e) · process (spawns a process, git or fork) · socket · sleep (real time.sleep) · db (sqlite) ·
fs-write (writes or creates a path) · fs-read (reads a path that is not the repo's own source) · repo-read (reads the checkout: the rules
that walk src) · pure (none of these). `declared` is the kind conftest gives it: real (a real/ folder or a real mark), e2e, else logic."""
import json
import sys
from collections import defaultdict
from pathlib import Path


def layer_of(node: str, row: dict) -> str:
    g = lambda *keys: sum(row.get(k, 0) for k in keys)  # noqa: E731
    if node.startswith("tests/e2e/"):
        return "e2e"
    if g("proc_spawn", "git_spawn", "fork"):
        return "process"
    if g("socket_connect", "socket_bind"):
        return "socket"
    if g("sleeps"):
        return "sleep"
    if g("sqlite_tmp", "sqlite_other", "sqlite_repo"):
        return "db"
    if g("write_tmp", "write_other", "write_repo"):
        return "fs-write"
    if g("read_tmp", "read_other"):
        return "fs-read"
    if g("read_repo"):
        return "repo-read"
    return "pure"


def declared(node: str) -> str:
    parts = node.split("::")[0].split("/")
    return "e2e" if parts[1] == "e2e" else "real" if "real" in parts[:-1] else "logic"


def load(folder: Path):
    touch, cpu = {}, {}
    for f in folder.glob("*.touch.json"):
        touch.update(json.loads(f.read_text()))
    for f in folder.glob("*.times.json"):
        for node, r in json.loads(f.read_text())["tests"].items():
            cpu[node] = sum(r.get(f"{p}_cpu", 0.0) for p in ("setup", "call", "teardown"))
    return touch, cpu


def main(folder: str) -> None:
    touch, cpu = load(Path(folder))
    total = sum(cpu.values()) or 1.0
    cells: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0.0])
    for node, row in touch.items():
        cell = cells[(layer_of(node, row), declared(node))]
        cell[0] += 1
        cell[1] += cpu.get(node, 0.0)
    print(f"{len(touch)} tests, {total:.0f} CPU s\n\nlayer x declared kind: tests | CPU s | share")
    for (lay, kind), (n, c) in sorted(cells.items(), key=lambda kv: -kv[1][1]):
        print(f"{lay:10s} {kind:6s} {n:5d} {c:8.1f} {100 * c / total:5.1f}%")
    print("\nlogic-declared tests that touch the filesystem or a db, by directory (tests | CPU s)")
    per: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for node, row in touch.items():
        if declared(node) == "logic" and layer_of(node, row) in ("fs-write", "fs-read", "db", "repo-read"):
            d = node.split("/")[1]
            per[d][0] += 1
            per[d][1] += cpu.get(node, 0.0)
    for d, (n, c) in sorted(per.items(), key=lambda kv: -kv[1][1])[:15]:
        print(f"{d:12s} {n:5d} {c:8.1f}")


if __name__ == "__main__":
    main(sys.argv[1])
