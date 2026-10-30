"""File-backed keyed documents and the ticket line (the lock table is adapters/locks.py)."""
import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from atomic_io import atomic_write_text

from taskloop.contracts import paths, wire
from taskloop.contracts.locks import Ticket
from taskloop.contracts.stores import JsonStore
from taskloop.stores.api import Doc

STALE_TMP = 600.0  # seconds after which a half-made ticket is garbage


class FileDocSet[T]:
    """One JsonStore per key, in the folder of `path_of(key)`; `keys()` lists the folder."""

    def __init__(self, path_of: Callable[[str], Path], cls: type[T]) -> None:
        self.path_of = path_of
        self.cls = cls

    def of(self, key: str) -> Doc[T]:
        return JsonStore(self.path_of(key), self.cls)

    def keys(self) -> list[str]:
        probe = self.path_of("x")
        try:
            names = [p.name for p in probe.parent.iterdir()]
        except OSError:
            return []
        return sorted(n[: -len(probe.suffix)] for n in names if n.endswith(probe.suffix) and not n.startswith("."))


class FileTickets:
    """Tickets appear whole (written aside, then linked in: a link never replaces a ticket another waiter made)."""

    def __init__(self, cfg: paths.ConfigDir) -> None:
        self.cfg = cfg

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None,
             bead: str = "") -> Ticket:
        folder = self.cfg.ticket(repo_key, 0).parent
        folder.mkdir(parents=True, exist_ok=True)
        counter = self.cfg.ticket_counter(repo_key)
        seq = max([self._last(counter), *(self._seq(p) for p in folder.iterdir())]) + 1
        while True:
            ticket = Ticket(pid=pid, why=why, since=now, prio=prio, seq=seq, pid_start=pid_start, bead=bead)
            tmp = folder / (f".{pid}.{threading.get_ident()}.{int(seq)}.tmp")  # threads of one process may race for a number
            tmp.write_text(json.dumps(wire.dump(ticket)), encoding="utf-8")
            try:
                os.link(tmp, self.cfg.ticket(repo_key, seq))
                if seq > self._last(counter):  # numbers only grow, also across an empty line; a lost race here is harmless
                    atomic_write_text(counter, str(seq), fsync=False)
                return ticket
            except FileExistsError:
                seq += 1
            finally:
                tmp.unlink(missing_ok=True)

    def line(self, repo_key: str) -> list[Ticket]:
        out: list[Ticket] = []
        folder = self.cfg.ticket(repo_key, 0).parent
        for tmp in folder.glob(".*.tmp") if folder.is_dir() else []:  # a waiter that died between writing and linking its ticket
            with contextlib.suppress(OSError):
                if time.time() - tmp.stat().st_mtime > STALE_TMP:
                    tmp.unlink()
        for p in sorted(folder.glob("*") if folder.is_dir() else []):
            if self._seq(p) == 0:
                continue
            try:
                ticket = wire.load(Ticket, json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # gone meanwhile, or not ours
            if ticket.alive():
                out.append(ticket)
            else:
                p.unlink(missing_ok=True)
        return sorted(out, key=lambda t: (t.prio, t.seq))

    def drop(self, repo_key: str, seq: int) -> None:
        with contextlib.suppress(OSError):
            self.cfg.ticket(repo_key, seq).unlink()

    @staticmethod
    def _last(counter: Path) -> int:
        try:
            return int(counter.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _seq(p: Path) -> int:
        return int(p.stem) if p.stem.isdigit() and not p.name.startswith(".") else 0
