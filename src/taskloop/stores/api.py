"""The store interfaces. Logic depends on these; `real.py` backs them with files, `memory.py` with dicts and lists.

A store is a typed document, a typed append-only log, a keyed set of documents, a lock table or a ticket line. Nothing here
names a file or a folder: where a thing lives is the real implementation's business (`taskloop.contracts.paths`).
"""
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from taskloop.contracts.enums import LockWhat
from taskloop.contracts.locks import LockRecord, Ticket
from taskloop.contracts.stores import Page


class Doc[T](Protocol):
    """One record, replaced whole. A missing, torn or stale (foreign `v`) record reads as None."""

    def read(self) -> T | None: ...
    def write(self, rec: T) -> None: ...
    def delete(self) -> None: ...


class DocSet[T](Protocol):
    """A keyed family of Docs (one per bead, one per ask)."""

    def of(self, key: str) -> Doc[T]: ...
    def keys(self) -> list[str]: ...


class Log[T](Protocol):
    """Append-only records read back by byte cursor; a torn tail waits, a foreign record is skipped and counted."""

    def append(self, rec: T) -> int: ...
    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[T]: ...
    def tail(self, n: int, before: int | None = None) -> Page[T]: ...


class LockTimeout(TimeoutError):
    """A wait for a lock ran out; `holder` is who had it (None when unreadable)."""

    def __init__(self, what: str, holder: LockRecord | None) -> None:
        super().__init__("%s held by %s" % (what, holder.holder if holder else "?"))
        self.holder = holder


class LockTable(Protocol):
    """Named locks, one holder at a time, across processes. The OS (or the fake) drops a lock when its process dies."""

    def hold(self, what: LockWhat, ident: str, holder: str, *, timeout: float | None = None,
             waiting: Callable[[LockRecord | None], None] | None = None) -> AbstractContextManager[LockRecord]:
        """Wait for the lock (forever, or `timeout` seconds then LockTimeout), hold it for the `with` block.
        `waiting` is called once, before the first wait, with the current holder. A holder whose pid is dead is broken."""
        ...

    def holder(self, what: LockWhat, ident: str) -> LockRecord | None:
        """Who holds it now; None when free."""
        ...


class Tickets(Protocol):
    """The line for a slot: a new ticket's number is past every live one; the line is (prio, seq) order; a dead waiter drops out."""

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None) -> Ticket: ...
    def line(self, repo_key: str) -> list[Ticket]: ...
    def drop(self, repo_key: str, seq: int) -> None: ...
