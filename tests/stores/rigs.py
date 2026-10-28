"""A rig builds one kind of Stores (file-backed or in-memory) and the few things only a test may do to it: tear a log's tail,
plant a lock held by another process, write a foreign document."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from taskloop.contracts import codec, paths  # noqa: E402
from taskloop.contracts.enums import LockWhat  # noqa: E402
from taskloop.contracts.locks import LockRecord  # noqa: E402
from taskloop.contracts.stores import JsonStore  # noqa: E402
from taskloop.stores.bundle import Stores  # noqa: E402
from taskloop.stores.memory import MemDoc, MemLockTable, MemLog, fake_stores  # noqa: E402
from taskloop.stores.real import real_stores  # noqa: E402

HOLDER = """
import json, sys, time
from pathlib import Path
import fcntl
path, record, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
f = open(path, "a+")
fcntl.flock(f, fcntl.LOCK_EX)
Path(path + ".holder").write_text(record)
print("held", flush=True)
time.sleep(secs)
"""


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class RealRig:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = paths.ConfigDir(Path(self.tmp.name) / "task-loop")
        self.stores: Stores = real_stores(self.cfg)
        self.procs: list[subprocess.Popen[str]] = []

    def close(self) -> None:
        for p in self.procs:
            p.kill()
            p.wait()
            if p.stdout:
                p.stdout.close()
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
        rec = json.dumps(codec.to_json(LockRecord(what=what, holder=holder, pid=pid, t=time.time())))  # pyrefly: ignore[unexpected-keyword]
        p = subprocess.Popen([sys.executable, "-c", HOLDER, str(path), rec, str(secs)], stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        assert p.stdout is not None and p.stdout.readline().strip() == "held"


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
