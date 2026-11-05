"""What a finished worker run leaves behind: its end (survivors, pids), its transcript's byte window, a file's size."""

from pathlib import Path

from delegate.adapters import procs
from delegate.app.supervisor import RunHooks
from delegate.contracts import codec
from delegate.contracts.json_types import Json, as_opt_int, as_opt_str


def worker_ended(res: dict[str, Json], hooks: RunHooks, launched: dict[str, Json]) -> dict[str, Json]:
    """The result with the worker's end attached; a done answer must not hide a worker still running."""
    wk = procs.worker_end(hooks.stops, as_opt_str(res.get("outcome")))
    pid, pgid = as_opt_int(launched.get("pid")), as_opt_int(launched.get("pgid"))
    if launched and pid is not None and pgid is not None:
        wk.pid, wk.pgid, wk.start = pid, pgid, as_opt_str(launched["start"])
    if wk.survivors and res.get("outcome") is None:  # a done answer must not hide a worker still running
        res.update(
            outcome="worker_survived", say="worker pids outlived SIGTERM and SIGKILL: " + ", ".join(str(x.pid) for x in wk.survivors)
        )
    return dict(res, worker=codec.to_json(wk))


def transcript_info(path: str | None, family: str, start: int = 0) -> dict[str, Json] | None:
    """-> {path, kind, from, to, bytes}: the transcript file and the byte window this call wrote (a resumed thread appends to one file), or
    None."""
    if not path:
        return None
    try:
        size = Path(path).stat().st_size
    except OSError:
        return None
    kind = {"claude": "claude", "openai": "codex"}.get(family, "opencode_export")
    frm = start if kind != "opencode_export" and 0 <= start <= size else 0  # an opencode export is rewritten whole each run
    return {"path": path, "kind": kind, "from": frm, "to": size, "bytes": size - frm}


def file_size(path: str | None) -> int:
    try:
        return Path(path).stat().st_size if path else 0
    except OSError:
        return 0
