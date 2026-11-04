"""Authoritative asks and their transition ledger; legacy files are import input only."""

import json
import logging
import time
from _thread import _local
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import override
from uuid import uuid4

from taskloop.contracts import factorydb, wire
from taskloop.contracts.ask import Ask
from taskloop.contracts.docstore import Absent, ForeignVersion, Item, JsonStore, Page, Present, Read, Torn
from taskloop.contracts.ledger import LedgerEntry
from taskloop.contracts.paths import ConfigDir


class Transaction(_local):
    def __init__(self) -> None:
        self.con: factorydb.sqlite3.Connection | None = None


class AskRows:
    """Documents and ledger share the active writer for the entire transition."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg
        self.active = Transaction()

    def connection(self) -> factorydb.sqlite3.Connection:
        con = self.active.con
        if con is None:
            try:
                self.cfg.root.mkdir(parents=True, exist_ok=True)
                con = factorydb.shared_rw(self.cfg.factory_db())
            except OSError as error:
                raise factorydb.DatabaseError("factory.db unavailable for asks") from error
        if con is None:
            raise factorydb.DatabaseError("factory.db unavailable for asks")
        return con

    def select(self, sql: str, args: tuple[str | int | None, ...] = ()) -> list[factorydb.sqlite3.Row]:
        """Rows of a read; no database yet means no rows, and a read never creates one."""
        if self.active.con is None and not self.cfg.factory_db().exists():
            return []
        return self.connection().execute(sql, args).fetchall()

    @contextmanager
    def transaction(self) -> Generator[None]:
        if self.active.con is not None:
            yield
        else:
            con = self.connection()
            with factorydb.begin_immediate(con):
                self.active.con = con
                try:
                    yield
                finally:
                    self.active.con = None

    def insert(self, bead: str, ask: Ask, *, missing_only: bool = False) -> bool:
        conflict = "DO NOTHING" if missing_only else (
            "DO UPDATE SET id=excluded.id,repo=excluded.repo,status=excluded.status,t=excluded.t,"
            "consumed=excluded.consumed,body=excluded.body,rev=ask.rev+1")
        cursor = self.connection().execute(
            "INSERT INTO ask(bead,id,repo,status,t,consumed,body) VALUES (?,?,?,?,?,?,?) ON CONFLICT(bead) " + conflict,
            (bead, ask.id, ask.repo, ask.status.value, ask.t, ask.consumed, json.dumps(wire.dump(ask), ensure_ascii=False)))
        return cursor.rowcount == 1


class DbDocs:
    def __init__(self, rows: AskRows) -> None:
        self.rows = rows

    def of(self, key: str) -> DbDoc:
        return DbDoc(self.rows, key)

    def keys(self) -> list[str]:
        return [row[0] for row in self.rows.select("SELECT bead FROM ask ORDER BY bead")]


class DbDoc(JsonStore[Ask]):
    def __init__(self, rows: AskRows, bead: str) -> None:
        super().__init__(rows.cfg.factory_db(), Ask)
        self.rows, self.bead = rows, bead

    @override
    def read(self) -> Read[Ask]:
        found = self.rows.select("SELECT body FROM ask WHERE bead=?", (self.bead,))
        return self.decode(found[0][0]) if found else Absent()

    @override
    def write(self, rec: Ask) -> None:
        with self.rows.transaction():
            self.rows.insert(self.bead, rec)

    @override
    def delete(self) -> None:
        with self.rows.transaction():
            self.rows.connection().execute("DELETE FROM ask WHERE bead=?", (self.bead,))


class DbLedger:
    def __init__(self, rows: AskRows) -> None:
        self.rows = rows

    def append(self, rec: LedgerEntry) -> int:
        with self.rows.transaction():
            return self.insert(rec, "ask:" + uuid4().hex) - 1

    def insert(self, rec: LedgerEntry, origin: str) -> int:
        cursor = self.rows.connection().execute(
            "INSERT INTO ask_ledger(t,event,ask,bead,repo,body,origin) VALUES (?,?,?,?,?,?,?) ON CONFLICT(origin) DO NOTHING",
            (rec.t, rec.event, rec.ask, rec.bead, rec.repo, json.dumps(wire.dump(rec), ensure_ascii=False), origin))
        return (cursor.lastrowid or 0) if cursor.rowcount else 0

    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[LedgerEntry]:
        rows = self.rows.select("SELECT id,body FROM ask_ledger WHERE id>? ORDER BY id LIMIT ?",
                                (offset, limit if limit is not None else -1))
        return _page(rows, offset)

    def tail(self, n: int, before: int | None = None) -> Page[LedgerEntry]:
        rows = self.rows.select("SELECT id,body FROM ask_ledger WHERE (? IS NULL OR id<=?) ORDER BY id DESC LIMIT ?",
                                (before, before, max(n, 0)))
        return _page(list(reversed(rows)), before or 0)


def _page(rows: Sequence[factorydb.sqlite3.Row], offset: int) -> Page[LedgerEntry]:
    items: list[Item[LedgerEntry]] = []
    for key, body in map(tuple, rows):
        try:
            items.append(Item(key - 1, key, wire.load(LedgerEntry, body)))
        except ValueError as error:
            raise factorydb.DatabaseError(f"unreadable ask ledger row: {key}") from error
    return Page(items, rows[-1][0] if rows else offset)


def read_snapshot(cfg: ConfigDir) -> tuple[list[Ask], list[LedgerEntry]]:
    """Dashboard-only read path: never initializes a DB or imports legacy files."""
    con = factorydb.open_ro(cfg.factory_db())
    if con is None:
        raise factorydb.DatabaseError("factory.db unavailable for asks")
    try:
        con.execute("BEGIN")
        asks: list[Ask] = []
        for (body,) in con.execute("SELECT body FROM ask ORDER BY t,bead"):
            try:
                asks.append(wire.load(Ask, body))
            except ValueError:
                continue  # Torn and foreign documents are listed by the owner's AskStore.
        ledger = _page(con.execute("SELECT id,body FROM ask_ledger ORDER BY id").fetchall(), 0)
        return asks, [item.rec for item in ledger.items]
    finally:
        con.close()


def has_legacy_asks(cfg: ConfigDir) -> bool:
    """Whether any ask file or ledger file is left to import; nothing there means nothing to open."""
    return cfg.ask_ledger().exists() or cfg.asks_dir().exists()


def import_legacy_asks(cfg: ConfigDir) -> tuple[int, list[str]]:
    """Import each source once, returning inserted rows and torn-file reports. Never modify source bytes."""
    rows = AskRows(cfg)
    count = 0
    torn: list[str] = []
    with rows.transaction():
        con = rows.connection()
        # Mark the family as well as each file: later files are never a second source of state.
        marker = str(cfg.asks_dir()) + "/.factory-import"
        if con.execute("SELECT 1 FROM source WHERE path=?", (marker,)).fetchone():
            return 0, []
        for bead in cfg.ask_beads():
            path = cfg.ask(bead)
            if not con.execute("SELECT 1 FROM source WHERE path=?", (str(path),)).fetchone():
                added, report = _import_document(rows, bead)
                count += added
                if report:
                    torn.append(report)
                    logging.getLogger(__name__).warning("Skipping torn legacy ask %s", report)
                _mark(con, str(path))
        count += _import_ledger(rows)
        _mark(con, marker)
    return count, torn


def _import_document(rows: AskRows, bead: str) -> tuple[int, str]:
    path = rows.cfg.ask(bead)
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return 0, f"{path}: {error}"
    rec = JsonStore(path, Ask).decode(body)
    added = 0
    if isinstance(rec, Present):
        added = int(rows.insert(bead, rec.rec, missing_only=True))
    elif isinstance(rec, ForeignVersion):
        # Keep orphan identity and the original version; it has no current Ask projection.
        cursor = rows.connection().execute(
            "INSERT INTO ask(bead,id,status,t,body) VALUES (?,?,'foreign',0,?) ON CONFLICT(bead) DO NOTHING",
            (bead, bead, body))
        added = cursor.rowcount
    return added, f"{path}: {rec.why}" if isinstance(rec, Torn) else ""


def _mark(con: factorydb.sqlite3.Connection, path: str) -> None:
    con.execute("INSERT INTO source(path,family,seen) VALUES (?,'ask',?)", (path, time.time()))


def _import_ledger(rows: AskRows) -> int:
    path = rows.cfg.ask_ledger()
    con = rows.connection()
    if con.execute("SELECT 1 FROM source WHERE path=?", (str(path),)).fetchone():
        return 0
    count, offset = 0, 0
    try:
        with path.open("rb") as source:
            ledger = DbLedger(rows)
            for line in source:
                try:
                    rec = wire.load(LedgerEntry, line)
                except ValueError:
                    pass
                else:
                    count += int(bool(ledger.insert(rec, f"legacy:{path}:{offset}")))
                offset += len(line)
    except FileNotFoundError:
        pass
    _mark(con, str(path))
    return count
