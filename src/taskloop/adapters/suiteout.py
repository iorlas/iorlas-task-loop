"""The text unittest prints: what a red suite shows, and N shards' outputs merged into one run's."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Shard:
    name: str
    code: int
    out: str


def failure_report(out: str) -> str:
    """Every "FAIL:" and "ERROR:" section of unittest output with its traceback, then the "Ran N tests" and "FAILED (..)" lines."""
    keep: list[str] = []
    in_section = False
    for line in out.splitlines():
        if line.startswith(("FAIL: ", "ERROR: ")):
            in_section = True
        elif line.startswith("Ran ") or line.startswith("FAILED ("):
            in_section = False
            keep.append(line)
            continue
        if in_section:
            keep.append(line)
    return "\n".join(keep)


def failing_tests(out: str) -> list[str]:
    return ["{} ({})".format(*m) for m in re.findall(r"^(?:FAIL|ERROR): (\S+) \(([^)]*)\)", out, re.M)]


def ran_seconds(out: str) -> float | None:
    m = re.search(r"^Ran \d+ tests? in ([\d.]+)s$", out, re.M)
    return float(m.group(1)) if m else None


def merge_outputs(parts: list[Shard], planned: int, wall: float | None = None) -> tuple[str, bool]:
    """One unittest-shaped output from the shards: their text without their own summaries, then a single "Ran N tests in <wall>s"
    and "OK" / "FAILED (..)". A shard that died without a summary, or a count that is not the planned one, is an ERROR."""
    body: list[str] = []
    total, secs = 0, 0.0
    bad = {"failures": 0, "errors": 0}
    other: dict[str, int] = {}
    for p in parts:
        ran = re.search(r"^Ran (\d+) tests? in ([\d.]+)s$", p.out, re.M)
        if not ran:
            last = "\n".join(p.out.splitlines()[-40:])
            body.append(f"ERROR: shard {p.name} crashed (exit {p.code}) without a summary\n{last}")
            bad["errors"] += 1
            continue
        total += int(ran.group(1))
        secs = max(secs, float(ran.group(2)))
        tail = re.search(r"^(?:OK|FAILED) ?\((.*)\)$", p.out, re.M)
        for k, v in re.findall(r"(\w[\w ]*?)=(\d+)", tail.group(1) if tail else ""):
            if k in bad:
                bad[k] += int(v)
            else:
                other[k] = other.get(k, 0) + int(v)
        cut = p.out.rfind("\n" + "-" * 70 + "\nRan ")
        body.append(p.out[:cut] if cut >= 0 else p.out)
        if p.code and not (bad["failures"] or bad["errors"]):
            body.append(f"ERROR: shard {p.name} exited {p.code} but reported no failure")
            bad["errors"] += 1
    if total != planned:
        body.append(f"ERROR: {total} tests ran, {planned} were planned")
        bad["errors"] += 1
    stats = ", ".join(f"{k}={v}" for k, v in [*bad.items(), *sorted(other.items())] if v)
    red = bool(bad["failures"] or bad["errors"])
    secs = wall if wall is not None else secs
    verdict = f"FAILED ({stats})" if red else (f"OK ({stats})" if stats else "OK")
    summary = f"Ran {total} tests in {secs:.3f}s\n\n{verdict}"
    return "\n".join(x for x in body if x.strip()) + "\n\n" + summary, not red
