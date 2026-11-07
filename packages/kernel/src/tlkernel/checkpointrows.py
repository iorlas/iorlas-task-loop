"""Atomic checkpoint cursors and stage sections, fenced by the cursor revision."""
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from tlkernel import factorydb, wire
from tlkernel.checkpoint import SECTION_TYPES, Checkpoint, CursorBody, join, split
from tlkernel.docrows import CHECKPOINT_DOCS, CHECKPOINT_SECTIONS, RowDoc, RowDocs, StaleRevision
from tlkernel.docstore import Absent, ForeignVersion, JsonStore, Present, Read, Torn, refusal
from tlkernel.paths import ConfigDir


class CheckpointRows:
    """One cursor and five sections per bead, committed together."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.docs = RowDocs(cfg, Checkpoint, table=CHECKPOINT_DOCS, key_col="bead", body_col="body", revisioned=True)
        self.rows = self.docs.rows

    def of(self, key: str) -> CheckpointDoc:
        return CheckpointDoc(self, key)

    def keys(self) -> list[str]:
        return self.docs.keys()

    def read(self, bead: str) -> Checkpoint | None:
        return self.of(bead).need()

    def write(self, ck: Checkpoint, expect_rev: int | None = None) -> None:
        self.of(ck.bead).write(ck, expect_rev=expect_rev)

    def delete(self, bead: str) -> None:
        self.of(bead).delete()


class CheckpointDoc(RowDoc[Checkpoint]):
    """The existing AmendDoc face over an assembled checkpoint."""

    def __init__(self, store: CheckpointRows, bead: str) -> None:
        super().__init__(store.docs, bead)
        self.store = store
        self.cursor = RowDocs(store.docs.cfg, CursorBody, table=CHECKPOINT_DOCS, key_col="bead",
                              body_col="body", revisioned=True).of(bead)

    def snapshot(self) -> tuple[Read[Checkpoint], int | None]:
        path = self.docs.cfg.factory_db()
        if not path.exists():
            return Absent(), None
        con = factorydb.open_ro(path)
        if con is None:
            return Absent(), None
        try:
            with con:
                con.execute("BEGIN")
                return self.read_in(con)
        finally:
            con.close()

    def read_in(self, con: sqlite3.Connection) -> tuple[Read[Checkpoint], int | None]:
        """Assemble the cursor, sections and revision from one database snapshot."""
        row = con.execute(f"SELECT body, rev FROM {CHECKPOINT_DOCS} WHERE bead=?", (self.k,)).fetchone()
        if row is None:
            return Absent(), None
        cursor = self.cursor.codec().decode(row[0])
        if not isinstance(cursor, Present):
            return cursor, int(row[1])
        sections = {}
        for name, cls in SECTION_TYPES.items():
            found = con.execute(f"SELECT body FROM {CHECKPOINT_SECTIONS} WHERE bead=? AND section=?",
                                (self.k, name)).fetchone()
            if found is None:
                return Torn(Path(self.k), f"missing {name} section"), int(row[1])
            section = JsonStore(Path(f"{self.k}/{name}"), cls).decode(found[0])
            if not isinstance(section, Present):
                return section, int(row[1])
            sections[name] = section.rec
        return Present(join(cursor.rec, sections)), int(row[1])

    def read(self) -> Read[Checkpoint]:
        return self.snapshot()[0]

    def write_in(self, con: sqlite3.Connection, rec: Checkpoint, *, expect_rev: int | None = None) -> None:
        if rec.bead != self.key:
            raise wire.Refused(f"checkpoint {self.key}: bead differs: {rec.bead}")
        cursor, sections = split(rec)
        self.cursor.write_in(con, cursor, expect_rev=expect_rev)
        stored = dict(con.execute(f"SELECT section, body FROM {CHECKPOINT_SECTIONS} WHERE bead=?", (self.k,)))
        for name, section in sections.items():
            body = json.dumps(wire.dump(section), ensure_ascii=False)
            if stored.get(name) == body:
                continue
            con.execute(f"INSERT INTO {CHECKPOINT_SECTIONS} (bead, section, body) VALUES (?, ?, ?) "
                        "ON CONFLICT(bead, section) DO UPDATE SET body=excluded.body "
                        f"WHERE {CHECKPOINT_SECTIONS}.body != excluded.body", (self.k, name, body))

    def _modify(self, fn: Callable[[Checkpoint], Checkpoint],
                also: Callable[[sqlite3.Connection | None], None] | None, tries: int) -> bool:
        for _ in range(tries):
            read, rev = self.snapshot()
            if isinstance(read, (Torn, ForeignVersion)):
                raise wire.Refused(refusal(read))
            if not isinstance(read, Present):
                if also is not None:
                    with self.docs.rows.transaction() as con:
                        also(con)
                return False
            new = fn(read.rec)
            try:
                with self.docs.rows.transaction() as con:
                    if also is not None:
                        also(con)
                    self.write_in(con, new, expect_rev=rev)
                return True
            except StaleRevision:
                continue
        raise StaleRevision(self.k)

    def delete(self) -> None:
        with self.docs.rows.transaction() as con:
            con.execute(f"DELETE FROM {CHECKPOINT_SECTIONS} WHERE bead=?", (self.k,))
            con.execute(f"DELETE FROM {CHECKPOINT_DOCS} WHERE bead=?", (self.k,))
