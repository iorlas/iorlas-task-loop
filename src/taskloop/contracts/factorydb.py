"""Schema v4 and conservative SQLite opens for the shared factory journal.

Connections belong to their caller's thread. Writers use begin_immediate for
short transactions; unavailable databases are reported as visible errors.
"""

import os
import sqlite3
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import override

import sqlite_store
from sqlite_store import SqlValue

from taskloop.contracts import dbparts, factorymigrate, factoryprune, wire
from taskloop.contracts.run import RunManifest

SCHEMA_VERSION = 5  # frozen: the parts (factoryparts, dbparts) carry the versions from here on
SCHEMA_READ_FROM = 4  # the oldest schema a read-only opener (the dashboard) reads as it is; lower this when a step stays readable

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
    "check_pass": "gate",
    "check_round": "gate",
    "ask": "engine",
    "ask_ledger": "engine",
    "kv": "index",
    "followup": "engine",  # the land's outbox (app/land/store.py)
    "effect": "engine",
    "wait": "loop",
    "signal": "owner",
    "timed": "engine",  # what the engine log's end records timed: tl runs show|slow read these
    "report_doc": "engine",  # the report part's reflect digest state (tl reflect)
    "release_doc": "engine",  # the release part's pin and last result (tl pin, tl release)
    "checkpoint": "engine",  # one row per bead across runs; the engine writes it with the revision it read
}
REVISIONED_TABLES = frozenset({"run", "ask", "bead", "checkpoint"})
# V1 held derived data only; preserve it before creating authoritative v2.
SCHEMA = sqlite_store.Schema(
    version=SCHEMA_VERSION,
    ddl="",
    steps=factorymigrate.STEPS,
    name="factory.db",
    revisioned=REVISIONED_TABLES,
    quarantine_versions=frozenset({1}),
    read_from=SCHEMA_READ_FROM,
)


class _PartStore(sqlite_store.Store):
    """The vendored store, plus the launch check of every declared part on each open (once per writer connection's file)."""

    def __init__(self, schema: sqlite_store.Schema) -> None:
        super().__init__(schema)
        self.parts: tuple[dbparts.Part, ...] | None = None
        self._launched: set[tuple[int, Path, int, int]] = set()

    @override
    def _open(self, path: str | os.PathLike[str], *, readonly: bool, shared: bool = False) -> sqlite3.Connection | None:
        if not readonly and self.parts is None:
            raise SchemaError("factory.db opened before this process declared its parts (factorydb.declare_parts)")
        con = super()._open(path, readonly=readonly, shared=shared)
        if con is None:
            return None
        try:
            if readonly:
                if self.parts is not None:
                    dbparts.launch(con, readonly=True, parts=self.parts)
            else:
                assert self.parts is not None
                stat = Path(path).resolve().stat()
                identity = (os.getpid(), Path(path).resolve(), stat.st_dev, stat.st_ino)
                if identity not in self._launched:
                    dbparts.launch(con, readonly=False, parts=self.parts)
                    self._launched.add(identity)
        except BaseException:
            con.close()
            raise
        return con


_STORE = _PartStore(SCHEMA)
SchemaError = sqlite_store.SchemaError


def declare_parts(parts: Sequence[dbparts.Part]) -> None:
    """Declare this process's parts once; repeated identical declarations are harmless."""
    declared = tuple(parts)
    if _STORE.parts is not None and _STORE.parts != declared:
        raise ValueError("factory.db parts already declared with a different list")
    _STORE.parts = declared
    # a fresh file is created whole, with its user_version, in one transaction
    _STORE.schema = replace(_STORE.schema, ddl=dbparts.ddl(declared))


def prune_older_than(
    con: sqlite3.Connection, cutoff_t: float, tables: tuple[str, ...] | None = None,
    keep_beads: frozenset[str] = frozenset(), dry_run: bool = False,
) -> dict[str, int]:
    """Prune the history declared by this process's parts."""
    if _STORE.parts is None:
        raise SchemaError("factory.db opened before this process declared its parts (factorydb.declare_parts)")
    return factoryprune.prune_older_than(
        con, cutoff_t, tables, keep_beads, dry_run, order=dbparts.prune_order(_STORE.parts))


def open_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open or initialize WAL; schema errors raise, unavailable storage returns None."""
    return _STORE.open_rw(path)


def open_ro(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open an existing compatible WAL database through SQLite's read-only URI."""
    return _STORE.open_ro(path)


def open_watch(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open read-only for a watcher whose caller serializes access across threads."""
    return _STORE._open(path, readonly=True, shared=True)


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


def attempt_of(path: Path, run: str) -> int | None:
    """The newest attempt number of a run (0: no row yet); None when the database cannot be read."""
    con = open_ro(path)
    if con is None:
        return None
    try:
        return con.execute("SELECT max(n) FROM attempt WHERE run=?", (run,)).fetchone()[0] or 0
    except sqlite3.Error:
        return None
    finally:
        con.close()
