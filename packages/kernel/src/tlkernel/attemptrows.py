"""Attempt history written under the run manifest's transaction."""

import os

from stream_proc import proc_start

from tlkernel import factorydb
from tlkernel.run import RunFinish, RunManifest, RunState


def ensure(con: factorydb.sqlite3.Connection, m: RunManifest, now: float | None = None) -> None:
    """Keep the counter's row with every manifest write; legacy rows are synthetic."""
    latest = con.execute("SELECT max(n) FROM attempt WHERE run=?", (m.run,)).fetchone()[0]
    if latest is not None and latest > m.attempts:
        raise factorydb.DatabaseError(f"attempt counter moved backwards: {m.run}")
    if now is not None:
        con.execute("UPDATE attempt SET ended=max(started,?), end_kind='yielded', reason='taken up by another process' "
                    "WHERE run=? AND ended IS NULL", (now, m.run))
    con.execute("INSERT INTO attempt (run,n,host,pid,start_id,started,beat,ended,reason) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(run,n) DO NOTHING",
                (m.run, m.attempts, os.uname().nodename if now is not None else m.host,
                 os.getpid() if now is not None else m.pid, proc_start(os.getpid()) if now is not None else None,
                 now if now is not None else m.started, now if now is not None else m.heartbeat,
                 None if now is not None else m.ended, None if now is not None else m.reason))


def close(con: factorydb.sqlite3.Connection, run: str, record: RunFinish, now: float) -> None:
    """Close an open attempt with the first terminal answer, including resumed close work."""
    kind = "finished"
    if record.state == RunState.LOST:
        kind = "lost"
    elif record.kind == "pause_killed":
        kind = "killed"
    elif record.state == RunState.STOPPED or record.kind.startswith("pause_") or record.kind == "engine_crash":
        kind = "yielded"
    elif record.state == RunState.PARKED or record.kind.startswith("ask_"):
        kind = "asked"
    con.execute("UPDATE attempt SET ended=max(started,COALESCE(beat,started),?), end_kind=?, reason=? "
                "WHERE run=? AND ended IS NULL", (now, kind, record.why, run))
