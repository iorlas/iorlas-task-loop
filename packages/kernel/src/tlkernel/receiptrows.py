"""Authoritative check receipts in factory.db; legacy files are import input only."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal

from tlkernel import factorydb, wire
from tlkernel.checks import BaseRedRecord, PassRecord
from tlkernel.docstore import Absent, Present, Read
from tlkernel.paths import ConfigDir

type Kind = Literal["pass", "base_red"]


class DbDocSet[T: (PassRecord, BaseRedRecord)]:
    """One repo/check/kind family; repo-wide base-red lookups span check IDs."""

    def __init__(self, cfg: ConfigDir, repo_key: str, check_id: str | None, kind: Kind, cls: type[T]) -> None:
        self.cfg, self.repo_key, self.check_id, self.kind, self.cls = cfg, repo_key, check_id, kind, cls

    def connection(self) -> factorydb.sqlite3.Connection:
        try:
            self.cfg.root.mkdir(parents=True, exist_ok=True)
            con = factorydb.shared_rw(self.cfg.factory_db())
        except OSError as error:
            raise factorydb.DatabaseError("factory.db unavailable for check receipts") from error
        if con is None:
            raise factorydb.DatabaseError("factory.db unavailable for check receipts")
        return con

    @contextmanager
    def transaction(self) -> Generator[factorydb.sqlite3.Connection]:
        con = self.connection()
        with factorydb.begin_immediate(con):
            yield con

    @property
    def where(self) -> str:
        return "repo_key=? AND kind=?" + (" AND check_id=?" if self.check_id is not None else "")

    @property
    def params(self) -> tuple[str, ...]:
        return (self.repo_key, self.kind) + ((self.check_id,) if self.check_id is not None else ())

    def exists(self) -> bool:
        try:
            self.cfg.factory_db().stat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise factorydb.DatabaseError("factory.db unavailable for check receipts") from error
        return True

    def of(self, key: str) -> DbDoc[T]:
        return DbDoc(self, key)

    def keys(self) -> list[str]:
        if not self.exists():
            return []
        rows = self.connection().execute("SELECT digest FROM check_pass WHERE " + self.where + " ORDER BY digest", self.params)
        return [row[0] for row in rows]

    def keep_newest(self, n: int) -> None:
        if n < 0 or self.kind != "pass" or self.check_id is None:
            raise ValueError("keep_newest requires a pass family and a nonnegative count")
        if self.exists():
            with self.transaction() as con:
                con.execute("DELETE FROM check_pass WHERE repo_key=? AND check_id=? AND kind='pass' AND rowid NOT IN "
                            "(SELECT rowid FROM check_pass WHERE repo_key=? AND check_id=? AND kind='pass' "
                            "ORDER BY ts DESC, digest DESC LIMIT ?)",
                            (self.repo_key, self.check_id, self.repo_key, self.check_id, n))

    def insert(self, con: factorydb.sqlite3.Connection, digest: str, rec: T, *, missing_only: bool = False) -> bool:
        if self.check_id is not None and rec.key.check != self.check_id:
            raise ValueError("receipt check does not match its family")
        tree = rec.tree if isinstance(rec, PassRecord) else rec.key.tree
        base = rec.base if isinstance(rec, PassRecord) else rec.key.base
        conflict = "DO NOTHING" if missing_only else (
            "DO UPDATE SET tree=excluded.tree,base=excluded.base,run=excluded.run,host=excluded.host,"
            "ts=excluded.ts,body=excluded.body")
        cursor = con.execute("INSERT INTO check_pass (repo_key,check_id,digest,kind,tree,base,run,host,ts,body) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(repo_key,check_id,digest,kind) " + conflict,
                             (self.repo_key, rec.key.check, digest, self.kind, tree, base, rec.run_id, rec.host, rec.ts,
                              json.dumps(wire.dump(rec), ensure_ascii=False)))
        return cursor.rowcount == 1


class DbDoc[T: (PassRecord, BaseRedRecord)]:
    def __init__(self, docs: DbDocSet[T], digest: str) -> None:
        self.docs, self.digest = docs, digest

    def get(self) -> T | None:
        if not self.docs.exists():
            return None
        row = self.docs.connection().execute("SELECT body FROM check_pass WHERE " + self.docs.where + " AND digest=?",
                                            (*self.docs.params, self.digest)).fetchone()
        try:
            return wire.load(self.docs.cls, row[0]) if row else None
        except (ValueError, TypeError) as error:
            raise factorydb.DatabaseError(f"unreadable check receipt: {self.digest}") from error

    def read(self) -> Read[T]:
        rec = self.get()
        return Present(rec) if rec is not None else Absent()

    def need(self) -> T | None:
        return self.get()

    def write(self, rec: T) -> None:
        with self.docs.transaction() as con:
            self.docs.insert(con, self.digest, rec)

    def delete(self) -> None:
        if self.docs.exists():
            with self.docs.transaction() as con:
                con.execute("DELETE FROM check_pass WHERE " + self.docs.where + " AND digest=?", (*self.docs.params, self.digest))
