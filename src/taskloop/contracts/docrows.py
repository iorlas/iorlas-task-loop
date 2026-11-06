"""Keyed documents in factory.db with the Doc / DocSet face of the file stores: a checkpoint is a `checkpoint` row (revisioned, so a
writer that read an older revision can be told), a follow-up outbox is a `kv` row. An older loop's file is adopted on the first read
of its key (dual-read, never dual-write). Forward-readable: a key this tl does not know is read past; a body of another `v` reads as
foreign, a torn one as torn, as the file store did."""
import contextlib
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
    def __init__(self, cfg: ConfigDir, cls: type[T], legacy: Callable[[str], Path], *, table: str, key_col: str, body_col: str,
                 prefix: str = "", revisioned: bool = False) -> None:
        self.rows, self.cfg, self.cls, self.legacy = LoopRows(cfg, ""), cfg, cls, legacy
        self.table, self.key_col, self.body_col, self.prefix, self.revisioned = table, key_col, body_col, prefix, revisioned

    def of(self, key: str) -> RowDoc[T]:
        return RowDoc(self, key)

    def keys(self) -> list[str]:
        found = self.rows.select(f"SELECT {self.key_col} FROM {self.table} ORDER BY {self.key_col}")
        keys = {k[len(self.prefix):] for (k,) in found if k.startswith(self.prefix)}
        probe = self.legacy("x")
        with contextlib.suppress(OSError):  # an older loop's files count until they are adopted
            keys |= {n[: -len(probe.suffix)] for p in probe.parent.iterdir() if (n := p.name).endswith(probe.suffix) and n[0] != "."}
        return sorted(keys)


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

    def legacy_store(self) -> JsonStore[T]:
        return JsonStore(self.docs.legacy(self.key), self.docs.cls)

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
            old = self.legacy_store().read()
            if isinstance(old, Present):
                self.write(old.rec)
            if not isinstance(old, Absent):
                with contextlib.suppress(OSError):
                    if isinstance(old, Present):
                        self.docs.legacy(self.key).unlink()
            return old
        return self.legacy_store().decode(self.forward(text))

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

    def delete(self) -> None:
        d = self.docs
        with d.rows.transaction() as con:
            con.execute(f"DELETE FROM {d.table} WHERE {d.key_col}=?", (self.k,))
        with contextlib.suppress(OSError):
            d.legacy(self.key).unlink()


class StaleRevision(ValueError):
    """The caller's revision no longer names the current row."""
