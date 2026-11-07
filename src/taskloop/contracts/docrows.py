"""Keyed documents in factory.db with the Doc / DocSet face of the file stores: a checkpoint is a `checkpoint` row (revisioned, so a
writer that read an older revision can be told), a follow-up outbox is a `kv` row. A key this tl does not know, a body of another `v` or a
torn one is refused (no backward compatibility)."""
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import wire
from taskloop.contracts.docstore import Absent, ForeignVersion, JsonStore, Present, Read, Torn, refusal
from taskloop.contracts.looprows import LoopRows
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.wire import Rec


class RowDocs[T: Rec]:
    def __init__(self, cfg: ConfigDir, cls: type[T], *, table: str, key_col: str, body_col: str,
                 prefix: str = "", revisioned: bool = False, quiet: bool = False) -> None:
        """`quiet` (the dashboard's read): a database that cannot be opened reads as no row."""
        self.quiet = quiet
        self.rows, self.cfg, self.cls = LoopRows(cfg, "", quiet=quiet), cfg, cls
        self.table, self.key_col, self.body_col, self.prefix, self.revisioned = table, key_col, body_col, prefix, revisioned

    def of(self, key: str) -> RowDoc[T]:
        return RowDoc(self, key)

    def keys(self) -> list[str]:
        found = self.rows.select(f"SELECT {self.key_col} FROM {self.table} ORDER BY {self.key_col}")
        return sorted({k[len(self.prefix):] for (k,) in found if k.startswith(self.prefix)})


class RowDoc[T: Rec]:
    def __init__(self, docs: RowDocs[T], key: str) -> None:
        self.docs, self.key = docs, key

    @property
    def k(self) -> str:
        return self.docs.prefix + self.key

    def raw(self) -> str | None:
        d = self.docs
        found = d.rows.select(f"SELECT {d.body_col} FROM {d.table} WHERE {d.key_col}=?", (self.k,))
        return found[0][0] if found else None

    def revision(self) -> int | None:
        """The row's revision, None when there is no row (or the table has none)."""
        d = self.docs
        if not d.revisioned:
            return None
        found = d.rows.select(f"SELECT rev FROM {d.table} WHERE {d.key_col}=?", (self.k,))
        return int(found[0][0]) if found else None

    def codec(self) -> JsonStore[T]:
        """The decoder of a body; the row's key is the name a refusal gives."""
        return JsonStore(Path(self.k), self.docs.cls)

    def read(self) -> Read[T]:
        text = self.raw()
        if text is None:
            return Absent()
        return self.codec().decode(text)

    def get(self) -> T | None:
        r = self.read()
        return r.rec if isinstance(r, Present) else None

    def need(self) -> T | None:
        r = self.read()
        if isinstance(r, (Torn, ForeignVersion)):
            raise wire.Refused(refusal(r))
        return r.rec if isinstance(r, Present) else None

    def write(self, rec: T, *, expect_rev: int | None = None) -> None:
        """Replace the row; `expect_rev` (a checkpoint's): refused with StaleRevision unless the row is still at that revision."""
        with self.docs.rows.transaction() as con:
            self.write_in(con, rec, expect_rev=expect_rev)

    def write_in(self, con: sqlite3.Connection, rec: T, *, expect_rev: int | None = None) -> None:
        """`write` inside the caller's transaction: opening another on the shared connection would close it (shared_rw drops a busy one)."""
        d = self.docs
        body = json.dumps(wire.dump(rec), ensure_ascii=False)
        if expect_rev is not None and d.revisioned:
            row = con.execute(f"SELECT rev FROM {d.table} WHERE {d.key_col}=?", (self.k,)).fetchone()
            if row is None or row[0] != expect_rev:
                raise StaleRevision(self.k)
        bump = f", rev={d.table}.rev+1" if d.revisioned else ""
        con.execute(f"INSERT INTO {d.table} ({d.key_col}, {d.body_col}, t) VALUES (?, ?, ?) "
                    f"ON CONFLICT({d.key_col}) DO UPDATE SET {d.body_col}=excluded.{d.body_col}, t=excluded.t{bump}",
                    (self.k, body, time.time()))

    def modify(self, fn: Callable[[T], T], tries: int = 8) -> bool:
        return self._modify(fn, None, tries)

    def modify_with(self, fn: Callable[[T], T], also: Callable[[sqlite3.Connection | None], None], tries: int = 8) -> bool:
        return self._modify(fn, also, tries)

    def _modify(self, fn: Callable[[T], T], also: Callable[[sqlite3.Connection | None], None] | None, tries: int) -> bool:
        """Read-modify-write one record: `fn` sees the stored record and its result replaces it only if no other writer got in between
        (the revision is checked in the write's transaction; a lost race re-reads and runs `fn` again). False when there is no record.
        `also(con)` runs in the same transaction, before the write: both land or neither (with no record it runs alone)."""
        for _ in range(tries):
            d = self.docs
            found = d.rows.select(f"SELECT {d.body_col}, rev FROM {d.table} WHERE {d.key_col}=?", (self.k,)) if d.revisioned else []
            read = self.codec().decode(found[0][0]) if found else None
            if isinstance(read, (Torn, ForeignVersion)):
                raise wire.Refused(refusal(read))
            if not isinstance(read, Present):
                if also is not None:
                    with d.rows.transaction() as con:
                        also(con)
                return False
            new = fn(read.rec)  # before the transaction: `fn` may write rows of its own
            try:
                with d.rows.transaction() as con:
                    if also is not None:
                        also(con)
                    self.write_in(con, new, expect_rev=int(found[0][1]))
                return True
            except StaleRevision:
                continue
        raise StaleRevision(self.k)

    def delete(self) -> None:
        d = self.docs
        with d.rows.transaction() as con:
            con.execute(f"DELETE FROM {d.table} WHERE {d.key_col}=?", (self.k,))


def singleton[T: Rec](cfg: ConfigDir, cls: type[T], name: str, quiet: bool = False, *, table: str = "kv") -> RowDoc[T]:
    """One cold document (a pin, a release result, a snapshot) as the row `name` of `table` (`kv`, or its owner's own table)."""
    return RowDocs(cfg, cls, table=table, key_col="k", body_col="v", prefix=name, quiet=quiet).of("")


class StaleRevision(ValueError):
    """The caller's revision no longer names the current row."""
