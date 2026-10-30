"""The store contract: every suite runs on the file-backed stores and on the in-memory ones. Real-FS only here: temp dirs, threads with
their own descriptors for the races (atomic replace, concurrent append, lock exclusion: flock and O_APPEND hold per open file, so
this is what two processes see), a real killed holder for the lock the OS drops."""
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
import jsonl_log as jsonl
import suites
from contracts import samples as S
from rigs import FakeRig, RealRig
from support.procsim import real_proc
from support.tiers import contract

from taskloop.adapters.locks import ProcessLockTable
from taskloop.contracts import paths
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.loop import Rest

SUITES = [suites.DocContract, suites.AskContract, suites.CheckpointContract, suites.LogContract, suites.LockContract,
          suites.TicketContract]


LIVE_HOLDER = "test_a_lock_whose_recorded_holder_is_alive_is_not_broken"


def _make(base: type, name: str, rig: type) -> type:
    body: dict = {"make_rig": lambda self: rig()}
    if rig is RealRig and hasattr(base, LIVE_HOLDER):  # the one test whose holder is another live process: only the real rig starts one
        def live_holder(self) -> None:
            getattr(base, LIVE_HOLDER)(self)
        body[LIVE_HOLDER] = real_proc("the lock's holder must be another live process: the real rig starts one")(live_holder)
    return contract(type(f"{name}{base.__name__}", (base,), body))


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

    def append_from(self, path: Path, n: int, tags: list[str]) -> list[threading.Thread]:
        """One writer per tag, each with its own Jsonl (own descriptors, as a process has): started, to be joined."""
        def write(tag: str) -> None:
            j = jsonl.Jsonl(path)
            for i in range(n):
                j.append({"who": tag, "i": i, "pad": "é" * (i % 50 + 1) * 40})
        ts = [threading.Thread(target=write, args=(tag,)) for tag in tags]
        for t in ts:
            t.start()
        return ts

    def test_many_writers_appending_never_interleave_a_line(self) -> None:
        path = self.cfg.root / "x.jsonl"
        for t in self.append_from(path, 60, [f"p{i}" for i in range(6)]):
            t.join(60)
        entries, cursor = jsonl.Jsonl(path).read_from(0)
        self.assertEqual(len(entries), 360)
        self.assertEqual(cursor, path.stat().st_size)
        for i in range(6):
            self.assertEqual([e.data["i"] for e in entries if e.data["who"] == f"p{i}"], list(range(60)))  # each writer's order holds
        self.assertEqual(len({e.start for e in entries}), 360)

    def test_a_reader_following_a_cursor_while_writers_append_sees_each_line_once(self) -> None:
        path = self.cfg.root / "y.jsonl"
        writers = self.append_from(path, 80, [f"p{i}" for i in range(3)])
        seen, cursor = [], 0
        while any(t.is_alive() for t in writers):
            entries, cursor = jsonl.Jsonl(path).read_from(cursor)
            seen += [(e.data["who"], e.data["i"]) for e in entries]
        entries, cursor = jsonl.Jsonl(path).read_from(cursor)
        seen += [(e.data["who"], e.data["i"]) for e in entries]
        self.assertEqual(len(seen), 240)
        self.assertEqual(len(set(seen)), 240)

    def test_a_reader_never_sees_half_a_document_while_writers_replace_it(self) -> None:

        doc = self.rig.stores.loop_rest("k")
        doc.write(S.other(Rest))
        stop = threading.Event()
        bad: list[object] = []

        def write() -> None:
            n = 0
            while not stop.is_set():
                n += 1
                doc.write(Rest(beads={f"b-{i}": float(n) for i in range(n % 40)}))

        w = threading.Thread(target=write)
        w.start()
        for _ in range(1500):
            if self.rig.stores.loop_rest("k").get() is None:
                bad.append("absent")
        stop.set()
        w.join()
        self.assertEqual(bad, [])
        self.assertEqual([p.name for p in cast(Any, doc).path.parent.iterdir()], [cast(Any, doc).path.name])  # no temp file left behind

    def test_holders_taking_one_lock_do_not_lose_updates(self) -> None:
        counter = self.cfg.root / "count.txt"
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text("0")

        def count() -> None:
            table = ProcessLockTable(paths.ConfigDir(str(self.cfg.root)))  # its own table: its own descriptors, like a process
            for _ in range(25):
                with table.hold(LockWhat.LAND, "r", "worker", timeout=60):
                    n = int(counter.read_text() or 0)  # read, then write: a lost update unless the lock really excludes
                    counter.write_text(str(n + 1))
        ts = [threading.Thread(target=count) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(90)
        self.assertEqual(int(counter.read_text()), 100)

    @real_proc("the file locks and the append-only log hold across real processes: races, a killed holder")
    def test_a_killed_holder_frees_its_lock_at_once(self) -> None:
        self.rig.plant_lock(LockWhat.AREA, "a", "victim", os.getpid())
        holder = self.rig.procs[-1]
        with self.assertRaises(TimeoutError), self.rig.stores.locks.hold(LockWhat.AREA, "a", "me", timeout=0.2):
            self.fail("took a held lock")
        holder.kill()  # a process this test forked
        with self.rig.stores.locks.hold(LockWhat.AREA, "a", "me", timeout=2) as rec:
            self.assertEqual(rec.holder, "me")

    def test_the_holder_file_is_a_json_record_of_the_holder(self) -> None:
        with self.rig.stores.locks.hold(LockWhat.LAND, "r", "tl-1"):
            data = json.loads(self.cfg.lock_record("land", "r").with_name("land-r.lock.holder").read_text())
        self.assertEqual((data["holder"], data["pid"], data["what"]), ("tl-1", os.getpid(), "land"))


if __name__ == "__main__":
    unittest.main()
