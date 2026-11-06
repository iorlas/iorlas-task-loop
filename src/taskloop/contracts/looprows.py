"""The loop's state, one `lease` row (kind `loop`) per loop process in factory.db: its LoopState in `body`, its pid and start in the
columns. A loop that died keeps its row renamed `died-<name>` as evidence (the file store kept `died-<pid>.json`). Its repo's stop
command and rests are `kv` rows."""
import contextlib
import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from taskloop.contracts import factorydb, wire
from taskloop.contracts.loop import LoopState
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import JsonStore

KIND = "loop"
DIED = "died-"


class LoopRows:
    def __init__(self, cfg: ConfigDir, key: str, *, quiet: bool = False) -> None:
        """`quiet`: a read that cannot open the database (corrupt, or a schema this tl does not know) answers nothing instead of
        raising. The dashboard reads that way, and shows the database's own error; everything else sees the error."""
        self.cfg, self.key, self.quiet = cfg, key, quiet

    @contextmanager
    def transaction(self) -> Generator[factorydb.sqlite3.Connection]:
        self.cfg.root.mkdir(parents=True, exist_ok=True)
        con = factorydb.shared_rw(self.cfg.factory_db())
        if con is None:
            raise factorydb.DatabaseError("factory.db unavailable for loop state")
        with factorydb.begin_immediate(con):
            yield con

    def select(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[str, ...]]:
        """A read, on a read-only connection (the dashboard reads this way too); none while there is no database or it cannot be opened."""
        if not self.cfg.factory_db().exists():
            return []
        try:
            con = factorydb.open_ro(self.cfg.factory_db())
            if con is None:
                return []
            try:
                return con.execute(sql, params).fetchall()
            finally:
                con.close()
        except factorydb.sqlite3.Error:  # a SchemaError (a schema this tl does not know) is one
            if self.quiet:
                return []
            raise

    def name(self, pid: int) -> str:
        return f"{self.key}.{pid}"

    def put(self, st: LoopState) -> None:
        body = json.dumps(wire.dump(st), ensure_ascii=False)
        with self.transaction() as con:
            con.execute("INSERT INTO lease (kind, name, holder, pid, since, beat, body) VALUES ('loop', ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(kind, name) DO UPDATE SET holder=excluded.holder, pid=excluded.pid, since=excluded.since, "
                        "beat=excluded.beat, body=excluded.body", (self.name(st.pid), st.actor, st.pid, st.started, st.t, body))

    def get(self, pid: int) -> LoopState | None:
        found = self.select("SELECT body FROM lease WHERE kind='loop' AND name=?", (self.name(pid),))
        return self.load(found[0][0]) if found else None

    def delete(self, pid: int) -> None:
        with self.transaction() as con:
            con.execute("DELETE FROM lease WHERE kind='loop' AND name=?", (self.name(pid),))

    def rows(self, prefix: str) -> list[LoopState]:
        """The loops of this repo whose row name starts with `prefix` ('' the live ones, DIED the dead), oldest first."""
        found = self.select("SELECT name, body FROM lease WHERE kind='loop'")
        want = prefix + self.key + "."
        mine = [self.load(body) for name, body in found if name.startswith(want) and (prefix or not name.startswith(DIED))]
        return sorted((st for st in mine if st is not None), key=lambda st: st.started)

    def mark_died(self, pid: int) -> None:
        with self.transaction() as con:
            con.execute("UPDATE lease SET name=? WHERE kind='loop' AND name=?", (DIED + self.name(pid), self.name(pid)))

    @staticmethod
    def load(text: str) -> LoopState | None:
        try:
            return wire.load(LoopState, json.loads(text))
        except (ValueError, TypeError):
            return None  # a torn or foreign-version body reads as absent, as the file store did


class KvDoc[T]:
    """One record of the repo's loop (its stop command, its rests) as a `kv` row; the same get / write / delete the file store had. An older
    loop's file at `legacy` is adopted on the first `get` (moved into the row, then removed: dual-read, never dual-write)."""

    def __init__(self, rows: LoopRows, key: str, tp: type[T], legacy: Path) -> None:
        self.rows, self.k, self.tp, self.legacy = rows, key, tp, legacy

    def get(self) -> T | None:
        found = self.rows.select("SELECT v FROM kv WHERE k=?", (self.k,))
        if found:
            return self.decode(found[0][0])
        old = JsonStore(self.legacy, self.tp).get()
        if old is not None:
            self.write(old)
        with contextlib.suppress(OSError):
            self.legacy.unlink()
        return old

    def write(self, rec: T) -> None:
        with self.rows.transaction() as con:
            con.execute("INSERT INTO kv (k, v, t) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, t=excluded.t",
                        (self.k, json.dumps(wire.dump(rec), ensure_ascii=False), time.time()))

    def delete(self) -> None:
        with self.rows.transaction() as con:
            con.execute("DELETE FROM kv WHERE k=?", (self.k,))
        with contextlib.suppress(OSError):
            self.legacy.unlink()

    def decode(self, text: str) -> T | None:
        try:
            return wire.load(self.tp, json.loads(text))
        except (ValueError, TypeError):
            return None
