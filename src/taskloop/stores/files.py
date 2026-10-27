"""File-backed keyed documents and the ticket line (the lock table is in filelock.py)."""
import contextlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import codec, paths
from taskloop.contracts.locks import Ticket
from taskloop.contracts.stores import JsonStore
from taskloop.stores.api import Doc


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

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None) -> Ticket:
        folder = self.cfg.ticket(repo_key, 0).parent
        folder.mkdir(parents=True, exist_ok=True)
        seq = max([0, *(self._seq(p) for p in folder.iterdir())]) + 1
        while True:
            ticket = Ticket(pid=pid, why=why, since=now, prio=prio, seq=seq, pid_start=pid_start)  # pyrefly: ignore[unexpected-keyword]
            tmp = folder / (".%d.%d.tmp" % (pid, seq))
            tmp.write_text(json.dumps(codec.to_json(ticket)), encoding="utf-8")
            try:
                os.link(tmp, self.cfg.ticket(repo_key, seq))
                return ticket
            except FileExistsError:
                seq += 1
            finally:
                tmp.unlink(missing_ok=True)

    def line(self, repo_key: str) -> list[Ticket]:
        out: list[Ticket] = []
        folder = self.cfg.ticket(repo_key, 0).parent
        for p in sorted(folder.glob("*") if folder.is_dir() else []):
            if self._seq(p) == 0:
                continue
            try:
                ticket = codec.from_json(Ticket, json.loads(p.read_text(encoding="utf-8")))
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
    def _seq(p: Path) -> int:
        return int(p.stem) if p.stem.isdigit() and not p.name.startswith(".") else 0
