"""Keyed documents in factory.db with the Doc / DocSet face of the file stores: a checkpoint is a `checkpoint` row (revisioned, so a
writer that read an older revision can be told), a follow-up outbox is a `kv` row. Forward-readable: a key this tl does not know is read
past; a body of another `v` reads as foreign, a torn one as torn, as the file store did."""
import json
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

    def forward(self, text: str) -> str:
        """Forward-readable: a key this tl does not know (a newer writer's) is read past, by its wire name."""
        try:
            body = json.loads(text)
        except ValueError:
            return text
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if k in wire.keys(self.docs.cls)}
        return json.dumps(body)

    def read(self) -> Read[T]:
        text = self.raw()
        if text is None:
            return Absent()
        return self.codec().decode(self.forward(text))

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
        d = self.docs
        body = json.dumps(wire.dump(rec), ensure_ascii=False)
        with d.rows.transaction() as con:
            if expect_rev is not None and d.revisioned:
                row = con.execute(f"SELECT rev FROM {d.table} WHERE {d.key_col}=?", (self.k,)).fetchone()
                if row is None or row[0] != expect_rev:
                    raise StaleRevision(self.k)
            bump = f", rev={d.table}.rev+1" if d.revisioned else ""
            con.execute(f"INSERT INTO {d.table} ({d.key_col}, {d.body_col}, t) VALUES (?, ?, ?) "
                        f"ON CONFLICT({d.key_col}) DO UPDATE SET {d.body_col}=excluded.{d.body_col}, t=excluded.t{bump}",
                        (self.k, body, time.time()))

    def modify(self, fn: Callable[[T], T], tries: int = 8) -> bool:
        """Read-modify-write one record: `fn` sees the stored record and its result replaces it only if no other writer got in between
        (the revision is checked in the write's transaction; a lost race re-reads and runs `fn` again). False when there is no record."""
        for _ in range(tries):
            self.get()  # adopts an older loop's file first, so the row and its revision exist
            d = self.docs
            found = d.rows.select(f"SELECT {d.body_col}, rev FROM {d.table} WHERE {d.key_col}=?", (self.k,)) if d.revisioned else []
            if not found:
                return False
            read = self.codec().decode(self.forward(found[0][0]))
            if isinstance(read, (Torn, ForeignVersion)):
                raise wire.Refused(refusal(read))
            if not isinstance(read, Present):
                return False
            try:
                self.write(fn(read.rec), expect_rev=int(found[0][1]))
                return True
            except StaleRevision:
                continue
        raise StaleRevision(self.k)

    def delete(self) -> None:
        d = self.docs
        with d.rows.transaction() as con:
            con.execute(f"DELETE FROM {d.table} WHERE {d.key_col}=?", (self.k,))


def singleton[T: Rec](cfg: ConfigDir, cls: type[T], name: str, quiet: bool = False) -> RowDoc[T]:
    """One cold document (a pin, a release result, a snapshot) as the `kv` row `name`."""
    return RowDocs(cfg, cls, table="kv", key_col="k", body_col="v", prefix=name, quiet=quiet).of("")


class StaleRevision(ValueError):
    """The caller's revision no longer names the current row."""
