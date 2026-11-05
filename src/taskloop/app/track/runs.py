"""`tl runs show ID` and `tl runs slow`: read-only queries over the engine log (engine/<run>.jsonl); no store of their own.

A row is one thing that ran or waited: a step, a worker call, a check, the gate or a wait. Its time is the end record's own
`exec_seconds` (a call's `secs`) and `wait_seconds`; nothing is recounted from timestamps."""
import json
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts import log
from taskloop.contracts.paths import ConfigDir


@dataclass(frozen=True)
class Item:
    run: str
    bead: str
    kind: str  # step | call | check | gate | wait
    name: str
    exec_s: float
    wait_s: float
    t: float


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
    """The timed things of one run, in the order they ended."""
    names: dict[str, tuple[str, str]] = {}
    out: list[Item] = []
    bead = ""
    for r in rows:
        bead = bead or r.bead
        if isinstance(r, log.StepStart):
            names[r.id] = ("step", r.step)
        elif isinstance(r, log.CallStart):
            names[r.id] = ("call", f"{r.node} {r.role}".strip())
        elif isinstance(r, log.CheckStart):
            names[r.id] = ("check", r.check)
        elif isinstance(r, log.WaitStart):
            names[r.id] = ("wait", str(r.what) + (f" {r.holder}" if r.holder else ""))
        elif isinstance(r, log.StepEnd | log.CheckEnd | log.WaitEnd):
            kind, name = names.get(r.id, ("step" if isinstance(r, log.StepEnd) else "?", r.id))
            out.append(Item(run, r.bead or bead, kind, name, r.exec_seconds or 0.0, r.wait_seconds or 0.0, r.t))
        elif isinstance(r, log.CallEnd):
            kind, name = names.get(r.id, ("call", r.id))
            out.append(Item(run, r.bead or bead, kind, name, r.secs, r.wait_seconds or 0.0, r.t))
        elif isinstance(r, log.GateEnd):
            out.append(Item(run, r.bead or bead, "gate", "gate", r.exec_seconds or 0.0, r.wait_seconds or 0.0, r.t))
    return out


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
    its = items(run, rows)
    bead = (start.bead if start else "") or (its[0].bead if its else "")
    print(f"run {run}  bead {bead or '-'}  branch {(start.branch if start else '') or '-'}")
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
    """The slowest timed items over the newest `runs` engine logs, by exec or by wait seconds."""
    try:
        logs = sorted(cfg.engine_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime)[-runs:]
    except OSError:
        logs: list[Path] = []
    every = [i for p in logs for i in items(p.stem, records(p))]
    def key(i: Item) -> float:
        return i.wait_s if by == "wait" else i.exec_s

    ranked = [i for i in sorted(every, key=key, reverse=True) if key(i) > 0][:top]
    if not ranked:
        print(f"no timed items in the newest {len(logs)} engine logs")
        return 0
    for i in ranked:
        print(f"{fmt(key(i)):>7} {by:<4} {i.kind:<6} {i.name:<40} {i.bead or '-':<14} {i.run}")
    return 0
