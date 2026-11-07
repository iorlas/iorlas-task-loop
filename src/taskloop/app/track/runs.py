"""`tl runs show ID` and `tl runs slow`: read-only queries over factory.db.

A row is one thing that ran or waited: a step, a worker call, a check, the gate, a wait or a command (contracts/timedrows.py: the engine
writes it as its log's end record is appended). Its time is the end record's own `exec_seconds` (a call's `secs`) and `wait_seconds`;
a command's is the gap between its start and end records. `show` also lists the run's attempts and, from the engine log, the head, the
artifacts and the close, which carry no seconds."""
import json
from dataclasses import dataclass
from pathlib import Path

from tlkernel import factorydb, log, timedrows
from tlkernel.paths import ConfigDir
from tlkernel.timedrows import Item


def records(path: Path) -> list[log.EngineLog]:
    """Every readable record of one engine log; a torn line or a record of a foreign version is skipped."""
    out: list[log.EngineLog] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            out.append(log.decode(json.loads(line)))
        except ValueError:  # msgspec.ValidationError and a foreign record version included
            continue
    return out


def items(run: str, rows: list[log.EngineLog]) -> list[Item]:
    """The timed things of a log, in the order they ended (what the engine writes as `timed` rows while it logs)."""
    tracker = timedrows.Tracker(run)
    return [i for r in rows if (i := tracker.feed(r)) is not None]


@dataclass(frozen=True)
class Attempt:
    n: int
    host: str
    pid: int
    started: float
    ended: float | None
    kind: str
    reason: str


def attempts_of(run: str, cfg: ConfigDir) -> list[Attempt]:
    """The run's attempts (a retry or a take-up inside one run id) from factory.db, opened read-only; none when it cannot be read."""
    try:
        con = factorydb.open_ro(cfg.factory_db())
    except factorydb.DatabaseError:
        return []
    if con is None:
        return []
    try:
        rows = con.execute("SELECT n, host, pid, started, ended, end_kind, reason FROM attempt WHERE run=? ORDER BY n", (run,)).fetchall()
    except factorydb.sqlite3.Error:
        return []
    finally:
        con.close()
    return [Attempt(r[0], r[1] or "", r[2] or 0, r[3], r[4], r[5] or "", r[6] or "") for r in rows]


def fmt(s: float) -> str:
    return f"{s / 60:.1f}m" if s >= 90 else f"{s:.0f}s"


def show(run: str, cfg: ConfigDir) -> int:
    """One run end to end: the head, then every timed item in order, then the close."""
    path = cfg.engine_log(run)
    if not path.exists():
        print(f"tl: no engine log for run {run} ({path})")
        return 1
    rows = records(path)
    start = next((r for r in rows if isinstance(r, log.RunStart)), None)
    close = next((r for r in reversed(rows) if isinstance(r, log.Close)), None)
    its = timedrows.of_run(cfg, run)
    bead = (start.bead if start else "") or (its[0].bead if its else "")
    print(f"run {run}  bead {bead or '-'}  branch {(start.branch if start else '') or '-'}")
    for a in attempts_of(run, cfg):
        end = f"{a.kind or 'ended'}: {a.reason}" if a.ended is not None else "open"
        span = f"{fmt(a.ended - a.started)}" if a.ended is not None else "-"
        print(f"  attempt {a.n} on {a.host or '?'} pid {a.pid}  {span}  {end}")
    for it in its:
        wait = f"  wait {fmt(it.wait_s)}" if it.wait_s else ""
        print(f"  {it.kind:<6} {it.name:<40} exec {fmt(it.exec_s):>6}{wait}")
    for r in rows:
        if isinstance(r, log.Artifacts):
            print(f"  artifacts {r.step}: {', '.join(r.names)}")
        elif isinstance(r, log.Evidence):
            print(f"  artifact {r.artifact}")
    total_e, total_w = sum(i.exec_s for i in its), sum(i.wait_s for i in its)
    ended = f"{close.outcome}: {close.why}" if close else "no close record (the run is live or died)"
    print(f"  total exec {fmt(total_e)}  wait {fmt(total_w)}  -> {ended}")
    return 0


def slow(cfg: ConfigDir, top: int, by: str, runs: int) -> int:
    """The slowest timed items over the newest `runs` runs with timed rows, by exec or by wait seconds."""
    seen, every = timedrows.newest(cfg, runs)

    def key(i: Item) -> float:
        return i.wait_s if by == "wait" else i.exec_s

    ranked = [i for i in sorted(every, key=key, reverse=True) if key(i) > 0][:top]
    if not ranked:
        print(f"no timed items in the newest {seen} runs")
        return 0
    for i in ranked:
        print(f"{fmt(key(i)):>7} {by:<4} {i.kind:<6} {i.name:<40} {i.bead or '-':<14} {i.run}")
    return 0
