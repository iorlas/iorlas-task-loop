"""The store contract: every suite runs on the file-backed stores and on the in-memory ones. Real-FS only here: temp dirs, real
processes for the races (atomic replace, concurrent append, lock exclusion across processes)."""
import json
import os
import signal
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
import suites  # noqa: E402
from rigs import FakeRig, RealRig  # noqa: E402
from support.tiers import contract  # noqa: E402
from taskloop.contracts import jsonl  # noqa: E402
from taskloop.contracts.enums import LockWhat  # noqa: E402

WORKER = str(Path(__file__).resolve().parent / "races_worker.py")
SUITES = [suites.DocContract, suites.AskContract, suites.CheckpointContract, suites.LogContract, suites.LockContract,
          suites.TicketContract]


def _make(base: type, name: str, rig: type) -> type:
    return contract(type("%s%s" % (name, base.__name__), (base,), {"make_rig": lambda self: rig()}))


for _base in SUITES:
    globals()["Real" + _base.__name__] = _make(_base, "Real", RealRig)
    globals()["Fake" + _base.__name__] = _make(_base, "Fake", FakeRig)
del _base


@contract
class RealRaces(unittest.TestCase):
    def setUp(self) -> None:
        self.rig = RealRig()
        self.addCleanup(self.rig.close)
        self.cfg = self.rig.cfg

    def spawn(self, *args: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen([sys.executable, "-I", WORKER, *args])

    def test_many_processes_appending_never_interleave_a_line(self) -> None:
        path = self.cfg.root / "x.jsonl"
        procs = [self.spawn("append", str(path), "60", "p%d" % i) for i in range(6)]
        self.assertEqual([p.wait(60) for p in procs], [0] * 6)
        entries, cursor = jsonl.Jsonl(path).read_from(0)
        self.assertEqual(len(entries), 360)
        self.assertEqual(cursor, path.stat().st_size)
        for i in range(6):
            self.assertEqual([e.data["i"] for e in entries if e.data["who"] == "p%d" % i], list(range(60)))  # each writer's order holds
        self.assertEqual(len({e.start for e in entries}), 360)

    def test_a_reader_following_a_cursor_while_processes_append_sees_each_line_once(self) -> None:
        path = self.cfg.root / "y.jsonl"
        procs = [self.spawn("append", str(path), "80", "p%d" % i) for i in range(3)]
        seen, cursor = [], 0
        while any(p.poll() is None for p in procs):
            entries, cursor = jsonl.Jsonl(path).read_from(cursor)
            seen += [(e.data["who"], e.data["i"]) for e in entries]
        entries, cursor = jsonl.Jsonl(path).read_from(cursor)
        seen += [(e.data["who"], e.data["i"]) for e in entries]
        self.assertEqual(len(seen), 240)
        self.assertEqual(len(set(seen)), 240)

    def test_a_reader_never_sees_half_a_document_while_writers_replace_it(self) -> None:
        from contracts import samples as S
        doc = self.rig.stores.loop_rest("k")
        doc.write(S.OTHERS["Rest"])
        stop = threading.Event()
        bad: list[object] = []

        def write() -> None:
            n = 0
            while not stop.is_set():
                n += 1
                doc.write(type(S.OTHERS["Rest"])(until=float(n), why="x" * (n % 400), t=0.0))  # pyrefly: ignore[unexpected-keyword]

        w = threading.Thread(target=write)
        w.start()
        for _ in range(1500):
            if self.rig.stores.loop_rest("k").read() is None:
                bad.append("absent")
        stop.set()
        w.join()
        self.assertEqual(bad, [])
        self.assertEqual([p.name for p in doc.path.parent.iterdir()], [doc.path.name])  # no temp file left behind

    def test_processes_taking_one_lock_do_not_lose_updates(self) -> None:
        counter = self.cfg.root / "count.txt"
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text("0")
        procs = [self.spawn("count", str(self.cfg.root), str(counter), "25") for _ in range(4)]
        self.assertEqual([p.wait(90) for p in procs], [0] * 4)
        self.assertEqual(int(counter.read_text()), 100)

    def test_a_killed_holder_frees_its_lock_at_once(self) -> None:
        self.rig.plant_lock(LockWhat.AREA, "a", "victim", os.getpid())
        holder = self.rig.procs[-1]
        with self.assertRaises(TimeoutError):
            with self.rig.stores.locks.hold(LockWhat.AREA, "a", "me", timeout=0.2):
                self.fail("took a held lock")
        os.kill(holder.pid, signal.SIGKILL)  # a pid this test started
        holder.wait()
        with self.rig.stores.locks.hold(LockWhat.AREA, "a", "me", timeout=2) as rec:
            self.assertEqual(rec.holder, "me")

    def test_the_lock_file_is_a_json_record_of_the_holder(self) -> None:
        with self.rig.stores.locks.hold(LockWhat.LAND, "r", "tl-1"):
            data = json.loads(self.cfg.lock_record("land", "r").read_text())
        self.assertEqual((data["holder"], data["pid"], data["what"]), ("tl-1", os.getpid(), "land"))


if __name__ == "__main__":
    unittest.main()
