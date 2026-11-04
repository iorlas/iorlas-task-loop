"""Daily verified factory snapshots and explicit, serialized doctor recovery."""

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from taskloop.contracts import factorydb
from taskloop.contracts.guard import guard
from taskloop.contracts.paths import ConfigDir


def backup_dir(cfg: ConfigDir) -> Path:
    """Snapshots stay beside the shared factory database."""
    return cfg.root / "backups"


def _check(path: Path) -> str:
    """Check an existing snapshot without creating or changing it."""
    try:
        if path.stat().st_size < 100:
            return "corrupt: truncated database"
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as con:
            rows = con.execute("PRAGMA quick_check").fetchall()
        return "" if rows == [("ok",)] else f"corrupt: {rows}"
    except (sqlite3.Error, OSError) as error:
        return f"corrupt or unopenable: {error}"


def _temporary(parent: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=".factory-", suffix=".tmp", dir=parent)
    os.close(fd)
    return Path(name)


def backup(cfg: ConfigDir, now: float) -> Path | None:
    """Publish at most one verified VACUUM snapshot per UTC day; keep seven."""
    target = backup_dir(cfg) / f"factory-{datetime.fromtimestamp(now, UTC):%Y%m%d}.db"
    if target.exists() or not cfg.factory_db().exists():
        return None
    with guard(cfg.lock_record("db-restore", "factory")):
        return _backup(cfg, target)


def _backup(cfg: ConfigDir, target: Path) -> Path | None:
    if target.exists():
        return None
    con = factorydb.open_ro(cfg.factory_db())
    if con is None:
        return None
    with closing(con):
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = _temporary(target.parent)
        try:
            con.execute("VACUUM INTO ?", (str(temp),))
            if reason := _check(temp):
                raise sqlite3.DatabaseError(reason)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    for old in sorted(target.parent.glob("factory-*.db"), reverse=True)[7:]:
        old.unlink()
    return target


def damaged(cfg: ConfigDir) -> str:
    """Return the reason storage is unavailable, or an empty string when healthy."""
    if not cfg.factory_db().exists():
        return "missing"
    try:
        con = factorydb.open_ro(cfg.factory_db())
        if con is None:
            return "unopenable or corrupt"
        with closing(con):
            rows = con.execute("PRAGMA quick_check").fetchall()
        return "" if rows == [("ok",)] else f"corrupt: {rows}"
    except (sqlite3.Error, OSError) as error:
        return f"unopenable or corrupt: {error}"


def restore(cfg: ConfigDir) -> Path | None:
    """Quarantine damaged storage and restore the newest verified snapshot, if any."""
    with guard(cfg.lock_record("db-restore", "factory")):
        if not damaged(cfg):
            return None
        factorydb.close_shared()
        factorydb.quarantine(cfg.factory_db())
        for source in sorted(backup_dir(cfg).glob("factory-*.db"), reverse=True):
            if not _check(source):
                temp = _temporary(cfg.root)
                try:
                    shutil.copyfile(source, temp)
                    if reason := _check(temp):
                        raise sqlite3.DatabaseError(reason)
                    # VACUUM snapshots use rollback journals; normalize through
                    # the usual writer open before publishing to WAL readers.
                    con = factorydb.open_rw(temp)
                    if con is None:
                        raise sqlite3.DatabaseError("restored factory.db is unopenable")
                    con.close()
                    os.replace(temp, cfg.factory_db())
                finally:
                    temp.unlink(missing_ok=True)
                return source
    return None
