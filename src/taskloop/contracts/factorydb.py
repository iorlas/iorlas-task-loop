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
  authority TEXT NOT NULL CHECK (authority IN ('files','dual','db')), since REAL NOT NULL);
CREATE TABLE source (path TEXT PRIMARY KEY, family TEXT NOT NULL,
  dev INTEGER, ino INTEGER, size INTEGER, mtime_ns INTEGER, head TEXT,
  offset INTEGER NOT NULL DEFAULT 0, seen REAL NOT NULL, error TEXT);
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
CREATE TABLE event (id INTEGER PRIMARY KEY, t REAL NOT NULL, src TEXT NOT NULL,
  kind TEXT NOT NULL, repo_key TEXT, bead TEXT, run TEXT, host TEXT, actor TEXT, session TEXT,
  body TEXT NOT NULL,
  origin TEXT NOT NULL UNIQUE);
CREATE INDEX event_t ON event(t);
CREATE INDEX event_run ON event(run, id);
CREATE INDEX event_bead ON event(bead, t);
CREATE INDEX event_repo ON event(repo_key, src, t);
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

# These are the authoritative writers; the indexer only projects file-owned rows.
# Shared lease/event rows require the per-row guards in the storage contract.
OWNERS: dict[str, str] = {
    "family": "index",
    "source": "index",
    "run": "engine",
    "attempt": "engine",  # Reconcile may mark lost only after a CAS on the expired lease.
    "step": "engine",
    "lease": "any:cas",
    "event": "any:cas",
    "check_pass": "engine",
    "check_round": "engine",
    "ask": "owner",
    "ask_ledger": "owner",
    "kv": "index",
    "effect": "engine",
    "wait": "loop",
    "signal": "owner",
}

type SqlValue = str | int | float | bytes | None


def _unsafe_fstype(fstype: str) -> bool:
    return fstype.lower().startswith(("nfs", "cifs", "fuse", "smb", "osxfuse", "macfuse"))


def _mount_path(value: str) -> Path:
    for escaped, plain in ((r"\040", " "), (r"\011", "\t"), (r"\012", "\n"), (r"\134", "\\")):
        value = value.replace(escaped, plain)
    return Path(value)


def _unsafe_filesystem(path: Path) -> bool:
    """Use the deepest mount, including for a database that does not yet exist."""
    with suppress(OSError, ValueError, RuntimeError):
        resolved = path.resolve()
        if sys.platform.startswith("linux"):
            mounts = []
            for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) >= 3:
                    mount = _mount_path(fields[1])
                    if resolved.is_relative_to(mount):
                        mounts.append((len(mount.parts), fields[2]))
            return bool(mounts) and _unsafe_fstype(max(mounts, key=lambda item: item[0])[1])
        if sys.platform == "darwin":
            probe = resolved if resolved.exists() else resolved.parent
            return _unsafe_fstype(getattr(os.statvfs(probe), "f_fstypename", ""))
    return False


def _journal_mode(con: sqlite3.Connection, *, readonly: bool) -> str:
    row = con.execute("PRAGMA journal_mode" if readonly else "PRAGMA journal_mode=WAL").fetchone()
    return str(row[0]).lower() if row else ""


def _schema_ready(con: sqlite3.Connection, *, readonly: bool) -> bool:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and not readonly:
        empty = con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
        if empty:
            # executescript commits a pending transaction first: BEGIN must be
            # inside the script so DDL and version publication are atomic.
            con.executescript(f"BEGIN IMMEDIATE;\n{DDL}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")
            version = SCHEMA_VERSION
    return version == SCHEMA_VERSION


def _open(path: str | os.PathLike[str], *, readonly: bool) -> sqlite3.Connection | None:
    con = None
    try:
        target = Path(path)
        if _unsafe_filesystem(target):
            return None
        address = f"{target.resolve().as_uri()}?mode=ro" if readonly else os.fspath(path)
        con = sqlite3.connect(address, uri=readonly, isolation_level=None, timeout=5.0)
        con.execute("PRAGMA busy_timeout=5000")
        if _journal_mode(con, readonly=readonly) != "wal":
            raise sqlite3.DatabaseError("WAL unavailable")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        if not _schema_ready(con, readonly=readonly):
            raise sqlite3.DatabaseError("unsupported schema version")
        if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("integrity check failed")
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
    if table not in OWNERS or "rev" in cols or key_col in cols:
        raise ValueError("unknown table or update of revision/key column")
    assignments = [f"{_identifier(column)}=?" for column in cols]
    assignments.append('"rev"="rev"+1')
    statement = f"UPDATE {_identifier(table)} SET {', '.join(assignments)} WHERE {_identifier(key_col)}=? AND rev=?"
    return con.execute(statement, (*cols.values(), key, rev)).rowcount == 1
