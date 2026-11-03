"""Schema v1 and conservative SQLite opens for the shared factory journal.

Connections belong to their caller's thread. Writers use begin_immediate for
short transactions; an unavailable database leaves the caller on file storage.
"""

import os
import sqlite3
import sys
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

SCHEMA_VERSION = 1
DDL = """
CREATE TABLE family (name TEXT PRIMARY KEY,
  authority TEXT NOT NULL CHECK (authority IN ('files','db')), since REAL NOT NULL);
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
  writer TEXT NOT NULL,
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
    "family": "index",
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
# Dashboard read-only opens skip quick_check; creation and version mismatches
# always check. Replacing the file invalidates the cache; in-place damage after
# a successful check is left to SQLite's normal read/write error handling.
_CHECKED: set[tuple[int, Path, int, int]] = set()

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
    """Use the deepest mount; detection errors mean the caller must fall back.

    Unknown types are allowed only on paths without a mount below root. This
    cannot identify a network-backed root filesystem; operators on such hosts
    must keep file storage. No external commands are run by this contract.
    """
    try:
        resolved = path.resolve()
        fstype = _filesystem_type(resolved)
        if fstype == "unknown":
            return any(os.path.ismount(parent) for parent in (resolved, *resolved.parents) if parent != Path(parent.anchor))
        return _unsafe_fstype(fstype)
    except (OSError, ValueError, RuntimeError):
        return None


def _journal_mode(con: sqlite3.Connection, *, readonly: bool) -> str:
    row = con.execute("PRAGMA journal_mode" if readonly else "PRAGMA journal_mode=WAL").fetchone()
    return str(row[0]).lower() if row else ""


def _schema_ready(con: sqlite3.Connection, *, readonly: bool) -> bool:
    """Initialize under the writer lock; return whether this open created it."""
    created = False
    version = con.execute("PRAGMA user_version").fetchone()[0]
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
    if version != SCHEMA_VERSION:
        con.execute("PRAGMA quick_check").fetchall()
        raise sqlite3.DatabaseError("unsupported schema version")
    return created


def _check_integrity(con: sqlite3.Connection, target: Path, *, created: bool, readonly: bool) -> None:
    stat = target.stat()
    identity = (os.getpid(), target.resolve(), stat.st_dev, stat.st_ino)
    if created or (not readonly and identity not in _CHECKED):
        if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("integrity check failed")
        _CHECKED.add(identity)


def _open(path: str | os.PathLike[str], *, readonly: bool) -> sqlite3.Connection | None:
    con = None
    try:
        target = Path(path)
        if _unsafe_filesystem(target) is not False:
            return None
        address = f"{target.resolve().as_uri()}?mode=ro" if readonly else os.fspath(path)
        con = sqlite3.connect(address, uri=readonly, isolation_level=None, timeout=5.0)
        con.execute("PRAGMA busy_timeout=5000")
        if _journal_mode(con, readonly=readonly) != "wal":
            raise sqlite3.DatabaseError("WAL unavailable")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        created = _schema_ready(con, readonly=readonly)
        _check_integrity(con, target, created=created, readonly=readonly)
        return con
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        if con is not None:
            with suppress(sqlite3.Error):
                con.close()
        return None


def open_rw(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open or initialize a WAL database, falling back on incompatible storage."""
    return _open(path, readonly=False)


def open_ro(path: str | os.PathLike[str]) -> sqlite3.Connection | None:
    """Open an existing compatible WAL database through SQLite's read-only URI."""
    return _open(path, readonly=True)


@contextmanager
def begin_immediate(con: sqlite3.Connection) -> Generator[None]:
    """Reserve the writer, committing on success and rolling back on failure."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.commit()
    except BaseException:
        con.rollback()
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
