"""Persist resumable engine-log facts alongside authoritative database run rows."""

import hashlib
import os
import time
from collections.abc import Callable

from taskloop.contracts import factorydb, log
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.receiptrows import import_legacy_receipts
from taskloop.contracts.runrows import import_legacy
from taskloop_dash import jsonl
from taskloop_dash.index.facts import Facts, append, decode, encode

HEAD = 256  # digest the first min(256, previous size) bytes before trusting a cursor
CHUNK = 256 * 1024


class Indexer:
    """One caller thread, one writable connection; every chunk commits source and facts together."""

    def __init__(self, cfg: ConfigDir, *, clock: Callable[[], float] = time.time,
                 on_record: Callable[[log.EngineLog | None], None] = lambda _: None) -> None:
        self.cfg, self.clock, self.on_record = cfg, clock, on_record
        self.locator = RunLocator(cfg)
        self.pending: list[RunBundle] | None = None
        self.found: set[str] = set()
        self.con = self._open()

    def _open(self):
        path = self.cfg.factory_db()
        self.cfg.root.mkdir(parents=True, exist_ok=True)
        con = factorydb.open_rw(path)
        if con is None:
            raise factorydb.DatabaseError("factory.db unavailable for indexing")
        return con

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.con.close()

    def clear(self) -> None:
        """Clear log folds and cursors while preserving authoritative state and revisions."""
        with factorydb.begin_immediate(self.con):
            self.con.execute("UPDATE run SET facts=NULL, facts_upto=NULL")
            self.con.execute("DELETE FROM source WHERE family='run'")
            self.con.execute("DELETE FROM kv WHERE k='index.run.pass'")
        self.pending = None

    def pass_once(self, budget: float = 0.2) -> bool:
        """Carry unfinished logs/scans to the next pass; return whether this sweep finished."""
        deadline = time.monotonic() + budget
        return self._pass(deadline)

    def _pass(self, deadline: float) -> bool:
        if self.pending is None:
            self.pending = list(reversed(self.locator.runs()))
            self.found = {b.run for b in self.pending}
        while self.pending:
            bundle = self.pending[-1]
            with factorydb.begin_immediate(self.con):
                done = self._run(bundle, deadline)
            if done:
                self.pending.pop()
            if time.monotonic() >= deadline:
                break
        finished = not self.pending
        with factorydb.begin_immediate(self.con):
            if finished:
                self._sweep()
                self.pending = None
            self.con.execute("INSERT INTO kv(k,v,t) VALUES ('index.run.pass','ok',?) "
                             "ON CONFLICT(k) DO UPDATE SET v=excluded.v,t=excluded.t", (self.clock(),))
        return finished

    def _sweep(self) -> None:
        active = {str(self.cfg.engine_log(run)) for run in self.found}
        for path, in self.con.execute("SELECT path FROM source WHERE family='run'").fetchall():
            if path not in active:
                self.con.execute("DELETE FROM source WHERE path=? AND family='run'", (path,))

    def _run(self, bundle: RunBundle, deadline: float) -> bool:
        row = self.con.execute("SELECT facts FROM run WHERE run=?", (bundle.run,)).fetchone()
        facts = decode(row[0] if row else None)
        source = self.con.execute("SELECT dev,ino,size,head,offset,mtime_ns,error FROM source WHERE path=?", (str(bundle.log),)).fetchone()
        try:
            with bundle.log.open("rb") as file:
                stat = os.fstat(file.fileno())
                prefix = file.read(HEAD)
                identity = (stat.st_dev, stat.st_ino)
                reset = source is None or identity != source[:2] or stat.st_size < source[2]
                if source and source[2] is not None and hashlib.sha256(prefix[:min(HEAD, source[2])]).hexdigest() != source[3]:
                    reset = True
                if (not reset and source and source[4] == stat.st_size and source[5] == stat.st_mtime_ns
                        and source[6] is None):
                    return True
                facts = Facts() if reset else facts
                offset = 0 if reset else source[4]
                file.seek(offset)
                data = file.read(CHUNK)
                if len(data) == CHUNK and b"\n" not in data:
                    data += file.readline()  # a single large record still makes progress
        except FileNotFoundError:
            self.con.execute("DELETE FROM source WHERE path=? AND family='run'", (str(bundle.log),))
            self._write(bundle, Facts(), 0)
            return True
        except OSError as error:
            self.con.execute("INSERT INTO source(path,family,seen,error) VALUES (?,'run',?,?) "
                             "ON CONFLICT(path) DO UPDATE SET seen=excluded.seen,error=excluded.error",
                             (str(bundle.log), self.clock(), str(error)))
            return True
        return self._chunk(bundle, facts, stat, prefix, offset, data, deadline)

    def _chunk(self, bundle: RunBundle, facts: Facts, stat: os.stat_result, prefix: bytes, offset: int,
               data: bytes, deadline: float) -> bool:
        rows: list[log.EngineLog] = []
        consumed = 0
        for raw in data.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                break
            record = jsonl.parse(raw.rstrip(b"\r\n"))
            self.on_record(record)
            if record is not None:
                rows.append(record)
            consumed += len(raw)
            if time.monotonic() >= deadline:
                break
        facts = append(facts, rows).replace(has_log=True, log_mtime=stat.st_mtime)
        offset += consumed
        self._write(bundle, facts, offset)
        self.con.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,NULL) ON CONFLICT(path) DO UPDATE SET "
                         "dev=excluded.dev,ino=excluded.ino,size=excluded.size,mtime_ns=excluded.mtime_ns,"
                         "head=excluded.head,offset=excluded.offset,seen=excluded.seen,error=NULL",
                         (str(bundle.log), "run", stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
                          hashlib.sha256(prefix).hexdigest(), offset, self.clock()))
        return offset >= stat.st_size or (consumed < len(data) and b"\n" not in data[consumed:])

    def _write(self, bundle: RunBundle, facts: Facts, offset: int) -> None:
        self.con.execute("UPDATE run SET facts=?, facts_upto=? WHERE run=?", (encode(facts), offset, bundle.run))


def reindex(cfg: ConfigDir, *, clock: Callable[[], float] = time.time) -> dict[str, float | int]:
    """The doctor's full rebuild uses exactly the worker's ingestion code."""
    start = time.monotonic()
    import_legacy(cfg)
    import_legacy_receipts(cfg)
    with Indexer(cfg, clock=clock) as index:
        index.clear()
        while not index.pass_once():
            pass
        counts = {table: index.con.execute(f"SELECT count(*) FROM {table} " +
                  ("" if table == "run" else "WHERE family='run'")).fetchone()[0]
                  for table in ("run", "source")}
    return {**counts, "seconds": time.monotonic() - start}
