"""The store interfaces. Logic depends on these; store implementations back them with persistent state or in-memory records.

A store is a typed document, a typed append-only log, a keyed set of documents, a lock table or a ticket line. Nothing here
names a file or a folder: where a thing lives is the real implementation's business (`tlkernel.paths`).
"""
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from tlkernel.checks import PassRecord
from tlkernel.docstore import Page, Read
from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord, Ticket


class Doc[T](Protocol):
    """One record, replaced whole. `read` says present, absent, torn or foreign version; `get` is the lossy view (all but present
    read as None) for a file that is a cache or can be derived again; `need` refuses a file that is there and cannot be read."""

    def read(self) -> Read[T]: ...
    def get(self) -> T | None: ...
    def need(self) -> T | None: ...
    def write(self, rec: T) -> None: ...
    def delete(self) -> None: ...


class AmendDoc[T](Doc[T], Protocol):
    """A Doc that can be rewritten from what it holds without losing another writer's change in between."""

    def modify(self, fn: Callable[[T], T]) -> bool: ...
    def modify_with(self, fn: Callable[[T], T], also: Callable[[sqlite3.Connection | None], None]) -> bool:
        """`modify`, and `also(con)` in the same transaction (con None: a store with none): both land or neither."""
        ...


class AmendSet[T](Protocol):
    def of(self, key: str) -> AmendDoc[T]: ...
    def keys(self) -> list[str]: ...


class DocSet[T](Protocol):
    """A keyed family of Docs (one per bead, one per ask)."""

    def of(self, key: str) -> Doc[T]: ...
    def keys(self) -> list[str]: ...


class Passes(DocSet[PassRecord], Protocol):
    """Pass receipts with atomic retention of the newest timestamps."""

    def keep_newest(self, n: int) -> None: ...


class Log[T](Protocol):
    """Append-only records read back by byte cursor; a torn tail waits, a foreign record is skipped and counted."""

    def append(self, rec: T) -> int: ...
    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[T]: ...
    def tail(self, n: int, before: int | None = None) -> Page[T]: ...


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

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None,
             bead: str = "") -> Ticket: ...
    def line(self, repo_key: str) -> list[Ticket]: ...
    def drop(self, repo_key: str, seq: int) -> None: ...
