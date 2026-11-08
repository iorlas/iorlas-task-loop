"""What a finished worker run leaves behind: its end (survivors, pids), its transcript's byte window, a file's size."""

from pathlib import Path

from any_agent.supervisor import RunHooks

from delegate.adapters import procs
from delegate.app import env
from delegate.app.lease import RunLease
from delegate.contracts import codec
from delegate.contracts import history as hist
from delegate.contracts.json_types import Json, arr, as_num, as_opt_int, as_opt_obj, as_opt_str, as_str, as_strs, obj
from delegate.domain.accounts.account import Account
from delegate.domain.health import ledger as health_ledger

SCHEMA_RAW_BYTES = 20 * 1024


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


def history_row(
    a: env.Args,
    res: dict[str, Json],
    d: dict[str, Json],
    account: Account,
    rid: str,
    lease: RunLease,
    cap: int | None,
    seen: tuple[str | None, str | None, float, bool, str],
) -> None:
    """The run's row in the history ledger: what the health ladder and the cockpit read."""
    ref, transcript, secs, done, detail = seen
    account_name = as_str(d["account"])
    ff = health_ledger.failure_fields(
        as_opt_str(res.get("outcome")), "", detail or as_opt_str(res.get("say")), as_num(res.get("retry_after"))
    )
    env.history_add(
        hist.RunRow(
            ts=env.now(),
            run_id=rid,
            call_id=getattr(a, "call_id", None),
            ref=ref,
            outcome=as_opt_str(ff.get("outcome")),
            fingerprint=as_opt_str(ff.get("fingerprint")),
            say=as_opt_str(ff.get("say")),
            until=as_num(ff.get("until")),
            role=a.role,
            task=a.task or "",
            account=account_name,
            model=as_str(d["model"]),
            effort=as_str(d["effort"]),
            done=done,
            warnings=as_strs(res.get("warnings")) if res.get("warnings") is not None else None,
            stream_tail=res.pop("stream_tail", None),
            schema_problem=as_opt_str(res.pop("schema_problem", None)),
            raw_answer=as_str(res.get("text")).encode("utf-8")[:SCHEMA_RAW_BYTES].decode("utf-8", errors="ignore")
            if res.get("outcome") == "schema_invalid"
            else None,
            denials=sum(1 for x in arr(res.get("denied")) if obj(x).get("kind") != "sandbox_limit"),
            secs=secs,
            cost=as_num(res.get("cost", 0)) or 0,
            tokens=as_opt_obj(res.get("tokens")),
            cumulative=as_opt_obj(res.get("cumulative")),
            five_before=account.five,
            week_before=account.week,
            overlap=lease.overlap,
            slots=cap,
            transcript=transcript,
        )
    )
