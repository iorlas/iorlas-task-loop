"""Read an engine run's typed log (EngineLog v3) in a test: the records as dicts, optionally of some kinds only."""
import json
from pathlib import Path


def records(run, *kinds):
    """The log's records as JSON dicts, in file order. `run` is an Engine (its log_path) or a path."""
    path = Path(getattr(run, "log_path", run))
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [r for r in recs if not kinds or r["kind"] in kinds]


def pairs(recs):
    """(start kinds without an end, end kinds without a start) by id: the pairs of the records that are not closed."""
    ends = {
        "step_end": "step_start",
        "call_end": "call_start",
        "cmd_end": "cmd_start",
        "check_end": "check_start",
        "wait_end": "wait_start",
    }
    starts = {v: k for k, v in ends.items()}
    opened = {(r["kind"], r["id"]) for r in recs if r["kind"] in starts}
    closed = {(ends[r["kind"]], r["id"]) for r in recs if r["kind"] in ends}
    return sorted(opened - closed), sorted(closed - opened)


def typed(kind, t, **fields):
    """One EngineLog v2 line as a dict."""
    return dict(v=3, kind=kind, t=t, **fields)


def write_log(path, recs):
    """Write dicts (from typed()) as a run's engine log; -> the path as a str."""
    Path(path).write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return str(path)
