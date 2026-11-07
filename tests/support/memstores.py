"""In-memory stores for logic tests. Each goes through the same wire form as the real one (a record that cannot be written to a
file cannot be written here) and the log is the real JsonlStore over an in-memory byte buffer, so cursors and torn tails behave
the same. The contract suite runs these and the file-backed stores through one set of tests."""
import contextlib
import json
import os
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, override

from jsonl_log import Entry, decode_object
from jsonl_log.cursor import _parse  # shelf lacks: a public parse of in-memory bytes

from support.memcheckpoints import MemCheckpointRows
from support.memdoc import MemDoc
from taskloop.stores.books import CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.files import temp_leases
from tlkernel import events, log, wire
from tlkernel.adrs import AdrStore
from tlkernel.ask import Ask
from tlkernel.askstore import AskStore
from tlkernel.checks import BaseRedRecord, CheckRun, Durations, PassRecord
from tlkernel.config import HostResources
from tlkernel.flakes import FlakeLog
from tlkernel.followups import FollowupOutbox
from tlkernel.ledger import Adr, AdrUse, LedgerEntry
from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord, LockTimeout, Ticket, pid_alive
from tlkernel.profile_changes import ProfileChange
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.rotating import RotatingJsonl
from tlkernel.storeapi import DocSet
from tlkernel.stores import JsonlStore
from tlkernel.trace import RunTrace


class MemDocSet[T](DocSet[T]):
    def __init__(self, cls: type[T]) -> None:
        self.cls = cls
        self.docs: dict[str, MemDoc[T]] = {}

    def of(self, key: str) -> MemDoc[T]:
        return self.docs.setdefault(key, MemDoc(self.cls))

    def keys(self) -> list[str]:
        return sorted(k for k, d in self.docs.items() if d.data is not None)

    def keep_newest(self, n: int) -> None:
        if n < 0:
            raise ValueError("keep_newest requires a nonnegative count")
        have = [(rec.ts, key) for key in self.keys() if isinstance(rec := self.of(key).get(), PassRecord)]
        for _, key in sorted(have, reverse=True)[n:]:
            self.of(key).delete()


class MemJsonl(RotatingJsonl):
    """The Jsonl file API over a bytearray, parsed by the same code."""

    def __init__(self) -> None:
        super().__init__(Path("memory"))
        self.buf = bytearray()

    @override
    def append(self, data: dict[str, Any]) -> int:
        line = (json.dumps(data, ensure_ascii=False, separators=(", ", ": ")) + "\n").encode("utf-8")
        start = len(self.buf)
        self.buf += line
        return start

    @override
    def size(self) -> int:
        return len(self.buf)

    @override
    def read_from(self, offset: int = 0, limit: int | None = None) -> tuple[list[Entry[dict[str, Any]]], int]:
        if offset > len(self.buf):
            offset = 0
        return _parse(bytes(self.buf[offset:]), offset, limit, decode_object)

    @override
    def tail(self, n: int, before: int | None = None) -> list[Entry[dict[str, Any]]]:
        end = len(self.buf) if before is None else min(before, len(self.buf))
        if n <= 0 or end == 0:
            return []
        entries, _ = _parse(bytes(self.buf[:end]), 0, None, decode_object)
        return entries[-n:]


class MemLog[T](JsonlStore[T]):
    def __init__(self, decode: Callable[[Any], T]) -> None:
        super().__init__(Path("memory"), decode)
        self.mem = MemJsonl()
        self.file = self.mem

    def tear(self, raw: bytes) -> None:
        """Test hook: bytes of a line another process has half written."""
        self.mem.buf += raw


def _decode(cls: type) -> Callable[[Any], Any]:
    return lambda data: wire.load(cls, data)


class MemLockTable:
    """Locks between threads of one test. A holder whose pid `alive` says is dead is broken, as the real table does."""

    def __init__(self, pid: int | None = None, alive: Callable[[int], bool] = pid_alive) -> None:
        self.pid = os.getpid() if pid is None else pid
        self.alive = alive
        self.held: dict[tuple[str, str], LockRecord] = {}
        self.cond = threading.Condition()

    @contextlib.contextmanager
    def hold(self, what: LockWhat, ident: str, holder: str, *, timeout: float | None = None,
             waiting: Callable[[LockRecord | None], None] | None = None) -> Generator[LockRecord]:
        key = (what.value, ident)
        end = None if timeout is None else time.monotonic() + timeout
        told = False
        with self.cond:
            while (cur := self.held.get(key)) is not None and self.alive(cur.pid):
                if waiting is not None and not told:
                    told = True
                    waiting(cur)
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    raise LockTimeout("{}-{}".format(*key), cur)
                self.cond.wait(0.05 if left is None else min(left, 0.05))
            rec = LockRecord(what=what, holder=holder, pid=self.pid, t=time.time())
            self.held[key] = rec
        try:
            yield rec
        finally:
            with self.cond:
                if self.held.get(key) is rec:
                    del self.held[key]
                self.cond.notify_all()

    def holder(self, what: LockWhat, ident: str) -> LockRecord | None:
        with self.cond:
            return self.held.get((what.value, ident))

    def plant(self, what: LockWhat, ident: str, rec: LockRecord) -> None:
        """Test hook: a lock some other process holds."""
        with self.cond:
            self.held[(what.value, ident)] = rec


class MemTickets:
    def __init__(self) -> None:
        self.rows: dict[str, dict[int, Ticket]] = {}
        self.last: dict[str, int] = {}  # numbers only grow, also across an empty line
        self.lock = threading.Lock()

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None,
             bead: str = "") -> Ticket:
        with self.lock:
            rows = self.rows.setdefault(repo_key, {})
            seq = max([self.last.get(repo_key, 0), *rows]) + 1
            self.last[repo_key] = seq
            rows[seq] = Ticket(pid=pid, why=why, since=now, prio=prio, seq=seq, pid_start=pid_start, bead=bead)
            return rows[seq]

    def line(self, repo_key: str) -> list[Ticket]:
        with self.lock:
            rows = self.rows.setdefault(repo_key, {})
            for seq in [s for s, t in rows.items() if not t.alive()]:
                del rows[seq]
            return sorted(rows.values(), key=lambda t: (t.prio, t.seq))

    def drop(self, repo_key: str, seq: int) -> None:
        with self.lock:
            self.rows.get(repo_key, {}).pop(seq, None)


def fake_stores(pid: int | None = None) -> Stores:
    """A whole fake process environment: nothing touches the disk."""
    runs: dict[str, MemLog[log.EngineLog]] = {}
    check_runs: dict[tuple[str, int | None], MemDoc[CheckRun]] = {}
    adrs: dict[str, AdrStore] = {}
    passes: dict[tuple[str, str], MemDocSet[PassRecord]] = {}
    reds: dict[str, MemDocSet[BaseRedRecord]] = {}
    return Stores(
        run_log=lambda run: runs.setdefault(run, MemLog(log.decode)),
        events=MemLog(events.decode), traces=MemLog(_decode(RunTrace)),
        profile_changes=MemLog(_decode(ProfileChange)),
        asks=AskStore(MemDocSet(Ask), MemLog(_decode(LedgerEntry))),
        adrs=lambda repo: adrs.setdefault(repo, AdrStore(MemDocSet(Adr), MemLog(_decode(AdrUse)))),
        checkpoints=CheckpointBook(MemCheckpointRows()),
        flakes=MemDocSet(FlakeLog),
        followups=MemDocSet(FollowupOutbox), queue=MemDocSet(QueueDoc), queue_state=MemDocSet(QueueState),
        results=lambda repo, check: passes.setdefault((repo, check), MemDocSet(PassRecord)),
        base_red=lambda repo: reds.setdefault(repo, MemDocSet(BaseRedRecord)),
        durations=MemDocSet(Durations),
        check_run=lambda run, rnd: check_runs.setdefault((run, rnd), MemDoc(CheckRun)),
        host=MemDoc(HostResources), locks=MemLockTable(pid), leases=temp_leases(), tickets=MemTickets())
