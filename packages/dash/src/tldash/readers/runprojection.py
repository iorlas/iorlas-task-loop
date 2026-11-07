"""The dashboard's run list and database health projection."""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tlkernel import factorydb, wire
from tlkernel.docrows import INDEX_DOCS
from tlkernel.run import RunManifest


def _run_health(con: sqlite3.Connection, now: float) -> str:
    stamp = con.execute(f"SELECT t FROM {INDEX_DOCS} WHERE k='index.run.pass'").fetchone()
    if stamp is None or now - stamp[0] > 5:
        return "database unavailable: indexer's last pass is older than 5 s"
    source = con.execute("SELECT error FROM source WHERE family='run' AND error IS NOT NULL LIMIT 1").fetchone()
    return f"database unavailable: run source unreadable: {source[0]}" if source else ""


def _readable(path: Path) -> tuple[sqlite3.Connection | None, str]:
    """The read-only connection, or why there is none; a schema this task-loop cannot read is named, never shown as an empty factory."""
    try:
        con = factorydb.open_ro(path)
    except factorydb.SchemaError as error:
        return None, f"database unavailable: {error}"
    if con is None:
        return None, "database unavailable: " + ("missing" if not path.exists() else "unopenable, corrupt, or incompatible schema")
    return con, ""


def database_error(path: Path, now: float) -> str:
    """Freshness check used even when a snapshot is cached; no run-file IO."""
    con, error = _readable(path)
    if con is None:
        return error
    try:
        return _run_health(con, now)
    except sqlite3.Error:
        return "database unavailable: corrupt or unreadable run data"
    finally:
        con.close()


@dataclass(frozen=True)
class RunRow:
    """Indexed manifest and encoded fold state; dashboard run projection."""

    manifest: RunManifest
    state: str
    has_log: bool
    log_mtime: float


def run_rows(path: Path, now: float, *, repo: str | None = None, bead: str | None = None) -> tuple[list[RunRow], str]:
    """One consistent DB read, including freshness; never consult a run file.

    Manifests belong to the engine; the indexer owns only log facts.
    """
    con, error = _readable(path)
    if con is None:
        return [], error
    try:
        con.execute("BEGIN")
        if error := _run_health(con, now):
            return [], error
        rows = con.execute(
            "SELECT manifest, COALESCE(json_extract(facts, '$.state'), '{}'), "
            "json_extract(facts, '$.has_log'), json_extract(facts, '$.log_mtime') "
            "FROM run WHERE (? IS NULL OR repo=?) AND (? IS NULL OR bead=?) ORDER BY started, run",
            (repo, repo, bead, bead)).fetchall()
        return [RunRow(wire.load(RunManifest, r[0]), r[1], bool(r[2]), r[3] or 0) for r in rows], ""
    except (sqlite3.Error, ValueError, TypeError):
        return [], "database unavailable: corrupt or unreadable run data"
    finally:
        con.close()
