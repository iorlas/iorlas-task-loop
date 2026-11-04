"""Schema v2 and conservative SQLite opens for the shared factory journal.

Connections belong to their caller's thread. Writers use begin_immediate for
short transactions; unavailable databases are reported as visible errors.
"""

import atexit
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts import factorymigrate, wire
from taskloop.contracts.factoryconnections import SharedConnections
from taskloop.contracts.guard import guard
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
# Successful writable checks are cached per resolved file identity, per process.
# Dashboard read-only opens skip quick_check; creation always checks.
# Replacing the file invalidates the cache; in-place damage after
# a successful check is left to SQLite's normal read/write error handling.
_CHECKED: set[tuple[int, Path, int, int]] = set()
_FILESYSTEMS: dict[str, bool] = {}
_FILESYSTEM_PID = [os.getpid()]
_SHARED = SharedConnections()
os.register_at_fork(after_in_child=_SHARED.after_fork)

type SqlValue = str | int | float | bytes | None


def _unsafe_fstype(fstype: str) -> bool:
    return fstype.lower().startswith(("nfs", "cifs", "fuse", "smb", "osxfuse", "macfuse"))


def _mount_path(value: str) -> Path:
    for escaped, plain in ((r"\040", " "), (r"\011", "\t"), (r"\012", "\n"), (r"\134", "\\")):
        value = value.replace(escaped, plain)
    return Path(value)


def _filesystem_type(resolved: Path) -> str:
    """Linux exposes mount types; statvfs has no portable filesystem type field.

    In particular, macOS statvfs cannot identify SMB/NFS. Without spawning or
    platform-specific ABI bindings, report unknown and reject mounted ancestors
    below root conservatively (even local removable disks).
    """
    fstype = "unknown"
    if sys.platform.startswith("linux"):
        mounts = []
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 3:
                mount = _mount_path(fields[1])
                if resolved.is_relative_to(mount):
                    mounts.append((len(mount.parts), fields[2]))
        if mounts:
            fstype = max(mounts, key=lambda item: item[0])[1]
    return fstype


def _unsafe_filesystem(path: Path) -> bool | None:
    """Use the deepest mount of a resolved path; errors prevent opening it.

    Unknown types are allowed only on paths without a mount below root. This
    cannot identify a network-backed root filesystem; operators must place the
    database on supported local storage. No external commands are run by this contract.
    """
    try:
        fstype = _filesystem_type(path)
        if fstype == "unknown":
            return any(os.path.ismount(parent) for parent in (path, *path.parents) if parent != Path(parent.anchor))
        return _unsafe_fstype(fstype)
    except (OSError, ValueError, RuntimeError):
        return None


def clear_filesystem_cache() -> None:
    """Forget mount verdicts, including when tests replace filesystem probes."""
    _FILESYSTEMS.clear()
    _FILESYSTEM_PID[0] = os.getpid()


def _filesystem_allowed(parent: Path) -> bool:
    if os.getpid() != _FILESYSTEM_PID[0]:
        clear_filesystem_cache()
    key = str(parent)
    if key not in _FILESYSTEMS:
        verdict = _unsafe_filesystem(parent)
        if verdict is None:
            return False
        _FILESYSTEMS[key] = verdict
    return not _FILESYSTEMS[key]


def _journal_mode(con: sqlite3.Connection, *, readonly: bool) -> str:
    """SQLite does not apply busy_timeout to a journal-mode switch: two openers of a fresh file race and one gets "database is
    locked" at once. Retry that within the same 5 s busy window."""
    deadline = time.monotonic() + 5.0
    while True:
        try:
            row = con.execute("PRAGMA journal_mode").fetchone()
            if not readonly and row and str(row[0]).lower() != "wal":
                row = con.execute("PRAGMA journal_mode=WAL").fetchone()
            return str(row[0]).lower() if row else ""
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _schema_ready(con: sqlite3.Connection, version: int, *, readonly: bool) -> bool:
    """Initialize under the writer lock; return whether this open created it."""
    created = False
    if version == 0 and not readonly:
        with begin_immediate(con):
            version = con.execute("PRAGMA user_version").fetchone()[0]
            empty = con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
            if version == 0 and empty:
                # Individual statements preserve the transaction (executescript
                # commits it first). DDL contains no triggers or embedded ';'.
                for statement in DDL.split(";"):
                    if statement.strip():
                        con.execute(statement)
                con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                version = SCHEMA_VERSION
                created = True
    if version > SCHEMA_VERSION:
        raise factorymigrate.SchemaError(
            f"factory.db is schema v{version}, this task-loop knows v{SCHEMA_VERSION}: update task-loop")
    if version < SCHEMA_VERSION and readonly:
        raise factorymigrate.SchemaError(
            f"factory.db is schema v{version}, this task-loop knows v{SCHEMA_VERSION}: the engine has not upgraded it yet")
    if 2 <= version < SCHEMA_VERSION:
        factorymigrate.upgrade(con, factorymigrate.STEPS, version, SCHEMA_VERSION)
    elif version != SCHEMA_VERSION:
        raise sqlite3.DatabaseError("unsupported schema version")
    return created


def _check_integrity(con: sqlite3.Connection, target: Path, *, created: bool, readonly: bool) -> None:
    stat = target.stat()
    identity = (os.getpid(), target, stat.st_dev, stat.st_ino)
    if created or (not readonly and identity not in _CHECKED):
        if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("integrity check failed")
        _CHECKED.add(identity)


def _open(path: str | os.PathLike[str], *, readonly: bool, shared: bool = False) -> sqlite3.Connection | None:
    con = None
    try:
        resolved = Path(path).resolve()
        if not _filesystem_allowed(resolved.parent):
            return None
        address = f"{resolved.as_uri()}?mode=ro" if readonly else os.fspath(path)
        con = sqlite3.connect(address, uri=readonly, isolation_level=None, timeout=5.0, check_same_thread=not shared)
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if not readonly and version == 1:
            con.close()
            _migrate_v1(resolved)
            con = sqlite3.connect(address, isolation_level=None, timeout=5.0, check_same_thread=not shared)
            version = con.execute("PRAGMA user_version").fetchone()[0]
        con.execute("PRAGMA busy_timeout=5000")
        if version > SCHEMA_VERSION or (readonly and version < SCHEMA_VERSION):
            _schema_ready(con, version, readonly=readonly)
        if _journal_mode(con, readonly=readonly) != "wal":
            raise sqlite3.DatabaseError("WAL unavailable")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        created = _schema_ready(con, version, readonly=readonly)
        _check_integrity(con, resolved, created=created, readonly=readonly)
        return con
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as error:
        if con is not None:
            with suppress(sqlite3.Error):
                con.close()
        if isinstance(error, factorymigrate.SchemaError):
            raise
        return None


def _migrate_v1(path: Path) -> None:
    """Serialize retirement and recheck after waiting for another opener."""
    with guard(path.with_suffix(".schema.lock")):
        probe = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        try:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        finally:
            probe.close()
        if version == 1:
            _retire_v1(path)


def _retire_v1(path: Path) -> None:
    """V1 contained derived data only; preserve it and initialize authoritative v2."""
    bad = quarantine(path)
    logging.getLogger(__name__).warning("Moved derived schema v1 to %s; creating factory.db schema v2", bad)


def quarantine(path: Path) -> Path:
    """Preserve a database and its sidecars together, leaving its original path free."""
    bad = path.with_name(f"{path.name}.bad-{time.time_ns()}")
    for suffix in ("", "-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.replace(Path(str(bad) + suffix))
    return bad


def open_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open or initialize WAL; schema errors raise, unavailable storage returns None."""
    return _open(path, readonly=False)


def open_ro(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open an existing compatible WAL database through SQLite's read-only URI."""
    return _open(path, readonly=True)


def shared_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Reuse this thread's idle writer only while its process and file identity match."""
    return _SHARED.get(path, lambda target: _open(target, readonly=False, shared=True))


def close_shared() -> None:
    """Close all writers cached by this process, including those of finished threads."""
    _SHARED.close()


atexit.register(close_shared)


@contextmanager
def begin_immediate(con: sqlite3.Connection) -> Generator[None]:
    """Reserve the writer, committing on success and rolling back on failure."""
    try:
        with factorymigrate.begin_immediate(con):
            yield
    except sqlite3.DatabaseError:
        _SHARED.discard(con)
        raise


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cas_update(con: sqlite3.Connection, table: str, key_col: str, key: SqlValue, rev: int, **cols: SqlValue) -> bool:
    """Update a revisioned row inside the caller's begin_immediate transaction."""
    if table not in REVISIONED_TABLES or "rev" in cols or key_col in cols:
        raise ValueError("unrevisioned table or update of revision/key column")
    if not con.in_transaction:
        raise ValueError("CAS requires a caller-owned transaction")
    assignments = [f"{_identifier(column)}=?" for column in cols]
    assignments.append('"rev"="rev"+1')
    statement = f"UPDATE {_identifier(table)} SET {', '.join(assignments)} WHERE {_identifier(key_col)}=? AND rev=?"
    return con.execute(statement, (*cols.values(), key, rev)).rowcount == 1


def change_counter(con: sqlite3.Connection) -> int:
    """Return data_version, which changes only when ANOTHER connection commits.

    A long-polling reader keeps its connection open and compares successive
    values on that connection; values from different connections do not compare.
    """
    return int(con.execute("PRAGMA data_version").fetchone()[0])


def prune_older_than(
    con: sqlite3.Connection,
    cutoff_t: float,
    tables: tuple[str, ...] = ("ask_ledger", "check_round", "step", "attempt", "effect", "run"),
) -> dict[str, int]:
    """Apply the sole age-retention path, atomically, to selected history tables.

    Run history ages from ended, never started. Retain runs referenced by any
    lease or wait, an unconsumed signal, or an open ask. Current state tables
    are never pruned. Subsets retain parents with remaining history children.
    The caller must not already have a transaction open.
    """
    order = ("ask_ledger", "check_round", "step", "attempt", "effect", "run")
    selected = set(tables)
    if selected - set(order):
        raise ValueError("only history tables may be pruned")
    eligible = """SELECT r.run FROM run AS r
        WHERE r.ended < ? AND r.state NOT IN ('created','running')
        AND NOT EXISTS (SELECT 1 FROM lease AS l WHERE l.run=r.run)
        AND NOT EXISTS (SELECT 1 FROM wait AS w WHERE w.run=r.run)
        AND NOT EXISTS (SELECT 1 FROM signal AS s WHERE s.run=r.run AND s.taken IS NULL)
        AND NOT EXISTS (SELECT 1 FROM ask AS a WHERE a.bead=r.bead AND a.status IN ('open','open_soft'))"""
    predicates = {
        "ask_ledger": """t < ?
            AND NOT EXISTS (SELECT 1 FROM ask AS a
                WHERE (a.id=ask_ledger.ask OR a.bead=ask_ledger.bead) AND a.status IN ('open','open_soft'))
            AND NOT EXISTS (SELECT 1 FROM run AS r
                WHERE r.bead=ask_ledger.bead AND r.state IN ('created','running'))""",
        "check_round": f"""ts < ? AND NOT EXISTS (
            SELECT 1 FROM run AS parent WHERE parent.run=check_round.run AND parent.run NOT IN ({eligible}))""",
        "step": f"run IN ({eligible})",
        "attempt": f"run IN ({eligible})",
        "effect": f"run IN ({eligible})",
        "run": f"""run IN ({eligible})
            AND NOT EXISTS (SELECT 1 FROM step WHERE step.run=run.run)
            AND NOT EXISTS (SELECT 1 FROM attempt WHERE attempt.run=run.run)
            AND NOT EXISTS (SELECT 1 FROM effect WHERE effect.run=run.run)
            AND NOT EXISTS (SELECT 1 FROM check_round WHERE check_round.run=run.run)""",
    }
    counts: dict[str, int] = {}
    with begin_immediate(con):
        for table in order:
            if table in selected:
                params = (cutoff_t, cutoff_t) if table == "check_round" else (cutoff_t,)
                counts[table] = con.execute(f'DELETE FROM "{table}" WHERE {predicates[table]}', params).rowcount
    return counts


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
    except factorymigrate.SchemaError as error:
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
