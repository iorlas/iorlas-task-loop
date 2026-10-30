"""A rig builds one kind of Stores (file-backed or in-memory) and the few things only a test may do to it: tear a log's tail,
plant a lock held by another process, write a foreign document."""
import contextlib
import fcntl
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import procsim

from taskloop.contracts import paths, wire
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.locks import LockRecord
from taskloop.contracts.stores import JsonStore
from taskloop.stores.bundle import Stores
from taskloop.stores.memory import MemDoc, MemLockTable, MemLog, fake_stores
from taskloop.stores.real import real_stores


class Holder:
    """A process that holds a lock: forked, so it is another process with its own file descriptions and no second interpreter."""

    def __init__(self, path: Path, record: str, secs: float) -> None:
        ready_r, ready_w = os.pipe()
        self.pid = os.fork()
        if self.pid == 0:
            try:
                os.close(ready_r)
                f = open(path, "a+")  # noqa: SIM115 (held open until the process ends)
                fcntl.flock(f, fcntl.LOCK_EX)
                Path(str(path) + ".holder").write_text(record)
                os.write(ready_w, b"held\n")
                time.sleep(secs)
            finally:
                os._exit(0)
        os.close(ready_w)
        with os.fdopen(ready_r) as r:
            assert r.readline().strip() == "held"
        self.alive = True

    def wait(self) -> None:
        if self.alive:
            os.waitpid(self.pid, 0)
            self.alive = False

    def kill(self) -> None:
        if self.alive:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, signal.SIGKILL)
            self.wait()


def dead_pid() -> int:
    return procsim.DEAD_PID


class RealRig:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = paths.ConfigDir(Path(self.tmp.name) / "task-loop")
        self.stores: Stores = real_stores(self.cfg)
        self.procs: list[Holder] = []

    def close(self) -> None:
        for p in self.procs:
            p.kill()
        self.tmp.cleanup()

    def tear(self, log: Any, raw: bytes) -> None:
        log.file.path.parent.mkdir(parents=True, exist_ok=True)
        with open(log.file.path, "ab") as f:
            f.write(raw)

    def poison(self, doc: Any, data: dict[str, Any]) -> None:
        assert isinstance(doc, JsonStore)
        doc.path.parent.mkdir(parents=True, exist_ok=True)
        doc.path.write_text(json.dumps(data), encoding="utf-8")

    def plant_lock(self, what: LockWhat, ident: str, holder: str, pid: int, secs: float = 30.0) -> None:
        """Another process holds the lock (flock) and its record names `pid`."""
        path = self.cfg.lock_record(what.value, ident)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = json.dumps(wire.dump(LockRecord(what=what, holder=holder, pid=pid, t=time.time())))  # pyrefly: ignore[unexpected-keyword]
        self.procs.append(Holder(path, rec, secs))


class FakeRig:
    def __init__(self) -> None:
        self.stores: Stores = fake_stores()

    def close(self) -> None:
        pass

    def tear(self, log: Any, raw: bytes) -> None:
        assert isinstance(log, MemLog)
        log.tear(raw)

    def poison(self, doc: Any, data: dict[str, Any]) -> None:
        assert isinstance(doc, MemDoc)
        doc.data = data

    def plant_lock(self, what: LockWhat, ident: str, holder: str, pid: int, secs: float = 30.0) -> None:
        assert isinstance(self.stores.locks, MemLockTable)
        self.stores.locks.plant(what, ident, LockRecord(what=what, holder=holder, pid=pid, t=time.time()))  # pyrefly: ignore[unexpected-keyword]
