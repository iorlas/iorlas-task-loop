"""Answers a run already took, indexed by call coordinates and semantic execution digest.

A prompt-only hash does not match the versioned execution identity: such a memo is refused.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tlkernel import factorydb, wire
from tlkernel.paths import ConfigDir
from tlkernel.run import CallIdentity, DoneEntry
from tlkernel.runrows import RunRows

from taskloop.app.workers import worker_identity


def _rows(run_dir: Path) -> RunRows:
    return RunRows(ConfigDir(run_dir.parent.parent))


def _entry(run_dir: Path, key: str) -> DoneEntry | None:
    with _rows(run_dir).transaction() as con:
        row = con.execute("SELECT result,input_digest FROM step WHERE run=? AND key=? AND try=1 AND status='done'",
                          (run_dir.name, key)).fetchone()
        if row is None:
            return None
        try:
            entry = wire.load(DoneEntry, row[0])
            if entry.sha != row[1]:
                raise ValueError("step digest disagrees with its receipt")
            return entry
        except (ValueError, TypeError) as error:
            raise factorydb.DatabaseError(f"unreadable consumed step: {run_dir.name} {key}") from error


def recall(
    run_dir: Path, key: tuple[Any, ...], sha: str, identity: CallIdentity | None = None,
) -> dict[str, Any] | None:
    """Reuse consumed work against its admitted inputs, before later engine effects."""
    entry = _entry(run_dir, json.dumps(list(key)))
    if entry is None:
        return None
    if entry.identity is not None and identity is not None:
        before = entry.identity
        if (before.semantics, before.worktree, before.cwd) != (identity.semantics, identity.worktree, identity.cwd):
            return None
        # A consumed step belongs to these coordinates in this run. Its worker,
        # checks and WIP save may have changed the checkout since admission.
        sha = worker_identity.execution_id(before)
    if entry.sha != sha:
        return None
    try:
        raw = json.loads(Path(entry.file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def keep(
    run_dir: Path, key: tuple[Any, ...], sha: str, answer_file: str, identity: CallIdentity | None = None,
) -> None:
    """The answer of the call at `key` was valid and used: remember where its raw copy is."""
    memo_in(run_dir, key, sha, answer_file, identity)(None)


def memo_in(
    run_dir: Path, key: tuple[object, ...], sha: str, answer_file: str, identity: CallIdentity | None = None,
) -> Callable[[sqlite3.Connection | None], None]:
    """`keep` as a step for a transaction that is already open (the connection), or its own when none is (None): what `settle` hands
    to the checkpoint's write, so the memo and the thread's updates land together."""
    def write(con: sqlite3.Connection | None) -> None:
        if not answer_file:
            return
        rows = _rows(run_dir)
        if con is None:
            with rows.transaction() as own:
                write(own)
            return
        m = rows.read(con, run_dir.name)
        if m is None:
            raise factorydb.DatabaseError(f"no run for consumed step: {run_dir.name}")
        now = time.time()
        entry = DoneEntry(sha=sha, file=answer_file, identity=identity)
        con.execute("INSERT INTO step (run,key,try,attempt,status,started,ended,input_digest,result,calls) "
                    "VALUES (?,?,1,?,'done',?,?,?,?,0) ON CONFLICT(run,key,try) DO UPDATE SET "
                    "attempt=excluded.attempt,status=excluded.status,started=excluded.started,ended=excluded.ended,"
                    "input_digest=excluded.input_digest,result=excluded.result,calls=excluded.calls",
                    (m.run, json.dumps(list(key)), m.attempts, now, now, sha, json.dumps(wire.dump(entry))))
    return write
