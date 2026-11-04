"""Schema v2 and conservative SQLite opens for the shared factory journal.

Connections belong to their caller's thread. Writers use begin_immediate for
short transactions; unavailable databases are reported as visible errors.
"""

import os
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import sqlite_store
from sqlite_store import SqlValue

from taskloop.contracts import factorymigrate, factoryprune, wire
from taskloop.contracts.run import RunManifest

SCHEMA_VERSION = 2
DDL = """
CREATE TABLE source (path TEXT PRIMARY KEY, family TEXT NOT NULL,
  dev INTEGER, ino INTEGER, size INTEGER, mtime_ns INTEGER, head TEXT,
  offset INTEGER NOT NULL DEFAULT 0, seen REAL NOT NULL, error TEXT);
CREATE TABLE bead (id TEXT PRIMARY KEY, repo_key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  priority INTEGER, type TEXT NOT NULL DEFAULT '', parent TEXT NOT NULL DEFAULT '', assignee TEXT NOT NULL DEFAULT '',
  labels TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL, fetched REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX bead_status ON bead(repo_key, status);
CREATE TABLE run (run TEXT PRIMARY KEY, repo TEXT NOT NULL, repo_key TEXT NOT NULL, bead TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT '', owner TEXT, session TEXT, loop TEXT, worktree TEXT, branch TEXT, sha TEXT,
  state TEXT NOT NULL, reason TEXT, started REAL NOT NULL, ended REAL, next_step TEXT,
  outcome TEXT, why TEXT, version TEXT, stats TEXT,
  bundle TEXT,
  facts TEXT, facts_upto INTEGER,
  manifest TEXT NOT NULL,
  rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX run_bead ON run(bead, started);
CREATE INDEX run_recent ON run(repo_key, started);
CREATE INDEX run_live ON run(state) WHERE state IN ('created','running');
CREATE TABLE attempt (run TEXT NOT NULL REFERENCES run, n INTEGER NOT NULL, host TEXT, pid INTEGER, start_id TEXT,
  started REAL NOT NULL, beat REAL, ended REAL, end_kind TEXT, fault_class TEXT, fingerprint TEXT, reason TEXT,
  PRIMARY KEY (run, n));
CREATE TABLE step (run TEXT NOT NULL REFERENCES run, key TEXT NOT NULL, try INTEGER NOT NULL, attempt INTEGER NOT NULL,
  status TEXT NOT NULL, started REAL NOT NULL, ended REAL, input_digest TEXT, result TEXT, fingerprint TEXT, calls INTEGER DEFAULT 0,
  PRIMARY KEY (run, key, try));
CREATE TABLE lease (kind TEXT NOT NULL CHECK (kind IN ('run','loop','resource','slot')), name TEXT NOT NULL,
  holder TEXT NOT NULL, run TEXT, host TEXT, pid INTEGER, start_id TEXT, since REAL NOT NULL, beat REAL, until REAL,
  body TEXT, PRIMARY KEY (kind, name));
CREATE TABLE check_pass (repo_key TEXT NOT NULL, check_id TEXT NOT NULL, digest TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('pass','base_red')), tree TEXT, base TEXT, run TEXT, host TEXT, ts REAL NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (repo_key, check_id, digest, kind));
CREATE INDEX check_tree ON check_pass(repo_key, tree, base);
CREATE TABLE check_round (run TEXT NOT NULL, round INTEGER NOT NULL, ts REAL, body TEXT NOT NULL, PRIMARY KEY (run, round));
CREATE TABLE ask (bead TEXT PRIMARY KEY, id TEXT NOT NULL, repo TEXT, status TEXT NOT NULL, t REAL NOT NULL, consumed REAL,
  body TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ask_live ON ask(status, t);
CREATE TABLE ask_ledger (id INTEGER PRIMARY KEY, t REAL NOT NULL, event TEXT NOT NULL, ask TEXT, bead TEXT, repo TEXT,
  body TEXT NOT NULL, origin TEXT NOT NULL UNIQUE);
CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, t REAL NOT NULL, stamp TEXT);
CREATE TABLE effect (
  key TEXT PRIMARY KEY,
  run TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL,
  intent_at REAL NOT NULL, done_at REAL, receipt TEXT
);
CREATE TABLE wait (
  id INTEGER PRIMARY KEY, repo TEXT NOT NULL, run TEXT, kind TEXT NOT NULL,
  wake_at REAL, wake_on TEXT, facts TEXT, since REAL NOT NULL, cleared REAL
);
CREATE TABLE signal (
  id INTEGER PRIMARY KEY, run TEXT, kind TEXT NOT NULL,
  payload TEXT, at REAL NOT NULL, taken REAL
);
"""

# One owner role per table: other actors submit writes through that role's store.
# The loop owns leases; the engine records AskStore writes, including
# owner answers. Lease reconciliation must use the loop store's guarded verbs,
# not cas_update (leases and the ask ledger have no revision column).
# DB-04+ must route today's engine park writes through the loop-owned wait store.
OWNERS: dict[str, str] = {
    "source": "index",
    "bead": "index",  # Cached tracker projection; parent is an opaque field.
    "run": "engine",
    "attempt": "engine",  # Reconcile may mark lost only after the loop guards the expired lease.
    "step": "engine",
    "lease": "loop",
    "check_pass": "engine",
    "check_round": "engine",
    "ask": "engine",
    "ask_ledger": "engine",
    "kv": "index",
    "effect": "engine",
    "wait": "loop",
    "signal": "owner",
}
REVISIONED_TABLES = frozenset({"run", "ask", "bead"})
# V1 held derived data only; preserve it before creating authoritative v2.
SCHEMA = sqlite_store.Schema(
    version=SCHEMA_VERSION,
    ddl=DDL,
    steps=factorymigrate.STEPS,
    name="factory.db",
    revisioned=REVISIONED_TABLES,
    quarantine_versions=frozenset({1}),
)
_STORE = sqlite_store.Store(SCHEMA)
SchemaError = sqlite_store.SchemaError


prune_older_than = factoryprune.prune_older_than


def open_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open or initialize WAL; schema errors raise, unavailable storage returns None."""
    return _STORE.open_rw(path)


def open_ro(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open an existing compatible WAL database through SQLite's read-only URI."""
    return _STORE.open_ro(path)


def shared_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Reuse this thread's idle writer while its process and file identity match."""
    return _STORE.shared_rw(path)


def close_shared() -> None:
    """Close all writers cached by this process after their operations stop."""
    _STORE.close_shared()


@contextmanager
def begin_immediate(con: sqlite3.Connection) -> Generator[None]:
    """Reserve the writer, committing on success and rolling back on failure."""
    with _STORE.begin_immediate(con):
        yield


def cas_update(con: sqlite3.Connection, table: str, key_col: str, key: SqlValue, rev: int, **cols: SqlValue) -> bool:
    """Update a revisioned row inside the caller's begin_immediate transaction."""
    return _STORE.cas_update(con, table, key_col, key, rev, **cols)


def change_counter(con: sqlite3.Connection) -> int:
    """Compare successive data_version values on this connection only."""
    return sqlite_store.change_counter(con)


def quarantine(path: Path) -> Path:
    """Preserve a database and its WAL/SHM sidecars after stopping its writers; a missing main file leaves only its stale sidecars
    to set aside (the package primitive needs the main file; shelf follow-up: tolerate its absence)."""
    if path.exists():
        return sqlite_store.quarantine(path)
    bad = path.with_name(f"{path.name}.bad-{time.time_ns()}")
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.replace(Path(str(bad) + suffix))
    return bad


def clear_filesystem_cache() -> None:
    """Forget mount verdicts after mount changes or replacement of a probe."""
    sqlite_store.clear_filesystem_cache()


DatabaseError = sqlite3.DatabaseError


def _run_health(con: sqlite3.Connection, now: float) -> str:
    stamp = con.execute("SELECT t FROM kv WHERE k='index.run.pass'").fetchone()
    if stamp is None or now - stamp[0] > 5:
        return "database unavailable: indexer's last pass is older than 5 s"
    source = con.execute("SELECT error FROM source WHERE family='run' AND error IS NOT NULL LIMIT 1").fetchone()
    return f"database unavailable: run source unreadable: {source[0]}" if source else ""


def _readable(path: Path) -> tuple[sqlite3.Connection | None, str]:
    """The read-only connection, or why there is none; a schema this task-loop cannot read is named, never shown as an empty factory."""
    try:
        con = open_ro(path)
    except SchemaError as error:
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
    """Indexed manifest and encoded fold state; no dashboard types cross this boundary."""

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
