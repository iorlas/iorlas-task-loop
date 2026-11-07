"""Best-effort loop exit evidence, shared by the loop and dead-process reconciliation."""
import contextlib
import json
import sys
from pathlib import Path


def rows(path: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and "reason" in rec and "pid" in rec:
                    found.append(rec)
    except OSError:
        pass
    return found


def loop_of(directory: Path, pid: int) -> int:
    for path in directory.glob("factory-loop-*.log"):
        try:
            if path.readlink().name == f"factory-{pid}.log":
                return int(path.stem.removeprefix("factory-loop-"))
        except (OSError, ValueError):
            continue
    return pid  # foreground loops have no numbered launcher link


def append(path: Path, rec: dict[str, object]) -> None:
    line = json.dumps(rec, ensure_ascii=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)
    except OSError as error:
        # Include the evidence itself: a full disk must never make the exit silent.
        with contextlib.suppress(OSError, ValueError):
            sys.stderr.write(f"{path.name}: write failed ({error}): {line}")
            sys.stderr.flush()


def record(directory: Path, rec: dict[str, object]) -> None:
    rec = {**rec, "loop": loop_of(directory, int(str(rec["pid"])))}
    append(directory / "factory.log", rec)
    append(directory / "exits.jsonl", rec)


def last_by_loop(directory: Path) -> list[dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for rec in rows(directory / "factory.log"):
        latest[str(rec.get("loop", rec["pid"]))] = rec
    return list(latest.values())
