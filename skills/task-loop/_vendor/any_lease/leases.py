"""The lease table: named resources of ``limit`` units each, kept as lock files under one folder."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

import process_lock

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_POLL = 0.5


@dataclass(frozen=True)
class Occupant:
    """One unit of a resource that looks taken: its slot and the record its holder wrote."""

    slot: int
    holder: process_lock.Holder | None  # None: taken, but its holder has not written a record yet


@dataclass(frozen=True)
class Waiting:
    """What ``on_wait`` is told on each poll while every unit is taken."""

    name: str
    limit: int
    elapsed: float
    occupants: tuple[Occupant, ...]


class LeaseTimeoutError(Exception):
    """Every unit of ``name`` stayed taken for the whole ``timeout``."""

    def __init__(self, name: str, limit: int, occupants: tuple[Occupant, ...]) -> None:
        self.name = name
        self.limit = limit
        self.occupants = occupants
        super().__init__(f"all {limit} unit(s) of {name!r} are taken")


class LeaseCancelledError(Exception):
    """``cancel`` was set while queuing: nothing is held."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"waiting for {name!r} was cancelled")


@dataclass
class Held:
    """One unit won. :meth:`release` is idempotent; the unit also goes with the process."""

    name: str
    slot: int
    waited: float
    _lock: process_lock.ProcessLock = field(repr=False)

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


@dataclass
class HeldAll:
    """Several resources won together, in name order. Releasing frees them in reverse."""

    held: tuple[Held, ...]
    waited: float

    def release(self) -> None:
        for one in reversed(self.held):
            one.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


class Leases:
    """The leases kept under ``root``. Two ``Leases`` on one folder share the same units."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def acquire(
        self,
        name: str,
        limit: int | None = None,
        *,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
        label: str | None = None,
        meta: Mapping[str, object] | None = None,
        on_wait: Callable[[Waiting], None] | None = None,
        poll: float = _POLL,
    ) -> Held:
        """Win one of the ``limit`` units of ``name``, queuing for it. ``limit`` may be omitted once the name is declared.

        ``timeout`` seconds to queue (0: try once, None: forever), then :class:`LeaseTimeoutError`. ``cancel`` set while queuing
        raises :class:`LeaseCancelledError`. ``label`` and ``meta`` (JSON-able) are the holder record waiters read.
        ``on_wait`` runs on every poll while all units are taken; an exception from it ends the wait.
        Nothing is held when any of these raises.
        """
        limit = self.declare(name, limit)
        began, queued = time.monotonic(), False
        while True:
            if cancel is not None and cancel.is_set():
                raise LeaseCancelledError(name)
            for slot in range(limit):
                lock = self._take(name, slot, label, meta)
                if lock is not None:
                    return Held(name, slot, time.monotonic() - began if queued else 0.0, lock)
            queued = True
            elapsed = time.monotonic() - began
            occupants = self.holders(name, limit)
            if timeout is not None and elapsed >= timeout:
                raise LeaseTimeoutError(name, limit, occupants)
            if on_wait is not None:
                on_wait(Waiting(name, limit, elapsed, occupants))
            pause = poll if timeout is None else max(0.0, min(poll, timeout - elapsed))
            if cancel is None:
                time.sleep(pause)
            else:
                cancel.wait(pause)

    def acquire_all(
        self,
        wants: _Wants,
        *,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
        label: str | None = None,
        meta: Mapping[str, object] | None = None,
        on_wait: Callable[[Waiting], None] | None = None,
        poll: float = _POLL,
    ) -> HeldAll:
        """Win one unit of each ``(name, limit)`` (or bare declared ``name``) in name order, whatever order the caller lists
        them, so two callers never wait on each other. ``timeout`` covers the whole set. A failure part way frees what was won."""
        pairs = sorted(_pairs(wants))
        end = None if timeout is None else time.monotonic() + timeout
        with contextlib.ExitStack() as stack:
            won: list[Held] = []
            for name, limit in pairs:
                left = None if end is None else max(0.0, end - time.monotonic())
                one = self.acquire(name, limit, timeout=left, cancel=cancel, label=label, meta=meta, on_wait=on_wait, poll=poll)
                stack.callback(one.release)
                won.append(one)
            stack.pop_all()
        return HeldAll(tuple(won), sum(one.waited for one in won))

    def declare(self, name: str, limit: int | None = None) -> int:
        """The limit of ``name``, kept in ``<root>/<name>.limit``: written by the first caller that gives one, then the same for
        everyone. A different ``limit`` raises ValueError, and so does an omitted one for a name never declared."""
        _check(name, limit)
        path = self.root / f"{name}.limit"
        known = _read_limit(path)
        if known is None and limit is not None:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / f".{name}.limit.{os.getpid()}.{threading.get_ident()}"
            tmp.write_text(str(limit), encoding="utf-8")
            try:
                os.link(tmp, path)  # atomic create-with-content: the first declarer wins, a reader never sees it half written
            except FileExistsError:
                pass
            finally:
                tmp.unlink(missing_ok=True)
            known = _read_limit(path)
        if known is None:
            msg = f"{name!r} has no declared limit; pass limit= or declare() it"
            raise ValueError(msg)
        if limit is not None and limit != known:
            msg = f"{name!r} is declared with limit {known}, not {limit}"
            raise ValueError(msg)
        return known

    def holders(self, name: str, limit: int | None = None) -> tuple[Occupant, ...]:
        """The units of ``name`` that are taken now, with the record each holder wrote (None when it wrote none yet).

        A unit counts only while its flock is held, found by a shared probe on a separate descriptor, dropped at once. The
        probe can make a ``timeout=0`` acquirer miss that unit in the same instant; waiters retry on their next poll.
        """
        limit = self.declare(name, limit)
        out: list[Occupant] = []
        for slot in range(limit):
            path = self._path(name, slot)
            if _is_held(path):
                out.append(Occupant(slot, process_lock.holder(path)))
        return tuple(out)

    def _path(self, name: str, slot: int) -> Path:
        return self.root / f"{name}-{slot}.lock"

    def _take(self, name: str, slot: int, label: str | None, meta: Mapping[str, object] | None) -> process_lock.ProcessLock | None:
        # reentrant=False: process-lock then refuses a second acquire of one path in this process, threads included.
        try:
            return process_lock.ProcessLock.acquire(
                self._path(name, slot), timeout=0, label=label, meta={**(meta or {}), "name": name, "slot": slot}, reentrant=False
            )
        except process_lock.LockHeldError:
            return None


type _Wants = Mapping[str, int | None] | Iterable[str | tuple[str, int | None]]


def _pairs(wants: _Wants) -> list[tuple[str, int | None]]:
    if isinstance(wants, Mapping):
        return list(cast("Mapping[str, int | None]", wants).items())  # narrowing by isinstance leaves the iterable half behind
    return [(w, None) if isinstance(w, str) else (w[0], w[1]) for w in wants]


def _check(name: str, limit: int | None) -> None:
    if not _NAME.fullmatch(name):
        msg = f"resource name {name!r} must match {_NAME.pattern}"
        raise ValueError(msg)
    if limit is not None and limit < 1:
        msg = f"limit must be at least 1, got {limit}"
        raise ValueError(msg)


def _read_limit(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _is_held(path: Path) -> bool:
    """Whether some open file description holds an exclusive flock on ``path``; creates nothing, keeps nothing."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)  # closing drops a probe lock too
    return False


__all__ = ["Held", "HeldAll", "LeaseCancelledError", "LeaseTimeoutError", "Leases", "Occupant", "Waiting"]
