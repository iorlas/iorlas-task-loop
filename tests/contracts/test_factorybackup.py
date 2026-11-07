"""Verified daily snapshots, bounded retention and explicit damage recovery."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tlkernel import factorybackup, factorydb
from tlkernel.paths import ConfigDir
from tltestkit.narrow import must

DAY = datetime(2026, 11, 4, tzinfo=UTC).timestamp()


@pytest.fixture
def cfg(tmp_path):
    return ConfigDir(tmp_path)


def seed(cfg, value="saved"):
    cfg.root.mkdir(parents=True, exist_ok=True)
    with closing(must(factorydb.open_rw(cfg.factory_db()))) as con:
        con.execute("INSERT INTO look_doc(k,v,t) VALUES ('test',?,1)", (value,))


def values(path):
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as con:
        assert con.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        return con.execute("SELECT k,v,t FROM look_doc ORDER BY k").fetchall()


def test_backup_once_per_utc_day(cfg):
    seed(cfg)
    first = must(factorybackup.backup(cfg, DAY))
    assert first == factorybackup.backup_dir(cfg) / "factory-20261104.db"
    before = first.stat()
    assert factorybackup.backup(cfg, DAY + 86399) is None
    assert first.stat() == before
    assert must(factorybackup.backup(cfg, DAY + 86400)).name == "factory-20261105.db"


def test_backup_keeps_seven_newest_names(cfg):
    seed(cfg)
    folder = factorybackup.backup_dir(cfg)
    folder.mkdir()
    for day in range(1, 12):
        (folder / f"factory-202610{day:02}.db").write_bytes(b"old")
    unrelated = folder / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    factorybackup.backup(cfg, DAY)
    assert sorted(path.name for path in folder.glob("factory-*.db")) == [
        *(f"factory-202610{day:02}.db" for day in range(6, 12)), "factory-20261104.db",
    ]
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_backup_contains_committed_wal_rows(cfg):
    seed(cfg)
    with closing(must(factorydb.open_rw(cfg.factory_db()))) as writer:
        writer.execute("INSERT INTO look_doc(k,v,t) VALUES ('wal','committed',2)")
        snapshot = must(factorybackup.backup(cfg, DAY))
        assert values(snapshot) == values(cfg.factory_db())
    assert sorted(path.name for path in snapshot.parent.iterdir()) == [snapshot.name]


def test_backup_missing_database_creates_nothing(tmp_path):
    cfg = ConfigDir(tmp_path / "absent")
    assert factorybackup.backup(cfg, DAY) is None
    assert not cfg.root.exists()


def test_backup_unopenable_database_creates_no_snapshot(cfg):
    cfg.factory_db().write_bytes(b"garbage" * 100)
    assert factorybackup.backup(cfg, DAY) is None
    assert not factorybackup.backup_dir(cfg).exists()
    assert cfg.factory_db().read_bytes() == b"garbage" * 100


def test_failed_snapshot_check_cleans_temp_without_pruning(cfg, monkeypatch):
    seed(cfg)
    first = must(factorybackup.backup(cfg, DAY))
    monkeypatch.setattr(factorybackup, "_check", lambda _: "corrupt: failed quick_check")
    with pytest.raises(sqlite3.DatabaseError, match="failed quick_check"):
        factorybackup.backup(cfg, DAY + 86400)
    assert list(first.parent.iterdir()) == [first]
    assert values(first) == [("test", "saved", 1.0)]


@pytest.mark.parametrize("content", [None, b"", b"SQLite format 3\x00", b"garbage" * 100])
def test_damaged_missing_truncated_and_garbage(cfg, content):
    if content is not None:
        cfg.factory_db().write_bytes(content)
    reason = factorybackup.damaged(cfg)
    assert reason
    assert ("missing" if content is None else "corrupt") in reason
    assert cfg.factory_db().exists() == (content is not None)


def test_damaged_healthy_database(cfg):
    seed(cfg)
    assert factorybackup.damaged(cfg) == ""


def test_restore_selects_newest_valid_backup(cfg):
    seed(cfg, "old")
    factorybackup.backup(cfg, DAY)
    with closing(must(factorydb.open_rw(cfg.factory_db()))) as con:
        con.execute("UPDATE look_doc SET v='new'")
    newest = must(factorybackup.backup(cfg, DAY + 86400))
    (newest.parent / "factory-20261106.db").write_bytes(b"garbage" * 100)
    (newest.parent / "factory-20261107.db").write_bytes(b"")
    cfg.factory_db().write_bytes(b"")
    assert factorybackup.restore(cfg) == newest
    assert values(cfg.factory_db()) == [("test", "new", 1.0)]
    assert factorybackup.damaged(cfg) == ""
    assert factorybackup.restore(cfg) is None
    assert len([p for p in cfg.root.glob("factory.db.bad-*") if not p.name.endswith(("-wal", "-shm"))]) == 1


def test_restore_preserves_bad_database_and_sidecars(cfg):
    seed(cfg)
    snapshot = must(factorybackup.backup(cfg, DAY))
    # Truncate a real DB after closing writers; preserve arbitrary broken sidecars.
    cfg.factory_db().write_bytes(b"not a database " * 20)
    for suffix in ("-wal", "-shm"):
        Path(str(cfg.factory_db()) + suffix).write_bytes(suffix.encode())
    assert factorybackup.restore(cfg) == snapshot
    bad = next(path for path in cfg.root.glob("factory.db.bad-*") if not path.name.endswith(("-wal", "-shm")))
    assert bad.read_bytes() == b"not a database " * 20
    assert Path(str(bad) + "-wal").read_bytes() == b"-wal"
    assert Path(str(bad) + "-shm").exists()  # SQLite may rewrite the shared-memory index itself
    assert values(cfg.factory_db()) == [("test", "saved", 1.0)]


def test_restore_leaves_healthy_database_untouched(cfg):
    seed(cfg)
    factorybackup.backup(cfg, DAY)
    before = cfg.factory_db().read_bytes(), cfg.factory_db().stat().st_ino
    assert factorybackup.restore(cfg) is None
    assert (cfg.factory_db().read_bytes(), cfg.factory_db().stat().st_ino) == before
    # stale sidecars of a missing database are set aside, never replayed onto the restored one
    assert not [p for p in cfg.root.glob("factory.db.bad-*") if not p.name.endswith(("-wal", "-shm"))]


@pytest.mark.parametrize("has_backup", [False, True])
def test_restore_without_valid_backup_leaves_path_free(cfg, has_backup):
    cfg.factory_db().write_bytes(b"broken")
    if has_backup:
        folder = factorybackup.backup_dir(cfg)
        folder.mkdir()
        (folder / "factory-20261104.db").write_bytes(b"garbage" * 100)
    assert factorybackup.restore(cfg) is None
    assert not cfg.factory_db().exists()
    assert next(cfg.root.glob("factory.db.bad-*")).read_bytes() == b"broken"
    seed(cfg, "rebuilt")
    assert factorybackup.damaged(cfg) == ""


def test_restore_missing_database_from_backup(cfg):
    seed(cfg)
    snapshot = must(factorybackup.backup(cfg, DAY))
    cfg.factory_db().unlink()
    assert factorybackup.restore(cfg) == snapshot
    assert factorybackup.damaged(cfg) == ""
    # stale sidecars of a missing database are set aside, never replayed onto the restored one
    assert not [p for p in cfg.root.glob("factory.db.bad-*") if not p.name.endswith(("-wal", "-shm"))]
