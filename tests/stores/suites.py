"""One suite per store family. Each is a mixin over `make_rig()`; test_contract.py runs it against the file-backed stores and
against the in-memory ones, so a fake cannot drift from the real thing without a test going red."""
import dataclasses
import os
import threading
import time
import unittest
from typing import Any

from rigs import dead_pid
from contracts import samples as S
from taskloop.contracts import codec, log as L
from taskloop.contracts.ask import Ask, AskAnswer
from taskloop.contracts.checkpoint import Unfiled
from taskloop.contracts.enums import AskStatus, LockWhat
from taskloop.contracts.locks import LockRecord
from taskloop.stores.api import LockTimeout

CK = S.OTHERS["Checkpoint"]


class Base(unittest.TestCase):
    def make_rig(self) -> Any:
        raise NotImplementedError

    def setUp(self) -> None:
        self.rig = self.make_rig()
        self.addCleanup(self.rig.close)
        self.s = self.rig.stores


class DocContract(Base):
    def test_a_missing_document_reads_as_none_and_a_write_reads_back_equal(self) -> None:
        doc = self.s.loop_state("k")
        self.assertIsNone(doc.read())
        doc.write(S.OTHERS["LoopState"])
        self.assertEqual(doc.read(), S.OTHERS["LoopState"])
        self.assertEqual(self.s.loop_state("k").read(), S.OTHERS["LoopState"])  # a new handle sees it
        self.assertIsNone(self.s.loop_state("other").read())

    def test_a_write_replaces_whole_and_delete_removes(self) -> None:
        doc = self.s.loop_rest("k")
        doc.write(S.OTHERS["Rest"])
        doc.write(dataclasses.replace(S.OTHERS["Rest"], why="lanes"))
        self.assertEqual(doc.read().why, "lanes")
        doc.delete()
        self.assertIsNone(doc.read())
        doc.delete()  # deleting nothing is fine

    def test_a_document_of_another_version_or_shape_reads_as_absent(self) -> None:
        doc = self.s.loop_command("k")
        self.rig.poison(doc, {"v": 99, "action": "resume", "by": "x", "t": 1.0})
        self.assertIsNone(doc.read())
        self.rig.poison(doc, {"v": 1, "action": "dance", "by": "x", "t": 1.0})
        self.assertIsNone(doc.read())
        doc.write(S.OTHERS["LoopCommand"])
        self.assertEqual(doc.read(), S.OTHERS["LoopCommand"])


class AskContract(Base):
    def raise_ask(self, bead: str, status: AskStatus = AskStatus.OPEN, t: float = S.T) -> Ask:
        a = dataclasses.replace(S.OTHERS["Ask"], bead=bead, id=bead + "-1", status=status, answer=None, answered=None, t=t)
        self.s.asks.of(bead).write(a)
        return a

    def test_live_lists_open_and_parked_asks_oldest_first(self) -> None:
        self.raise_ask("b2", t=S.T + 5)
        self.raise_ask("b1", AskStatus.PARKED, t=S.T)
        self.raise_ask("b3", AskStatus.WITHDRAWN)
        self.assertEqual([a.bead for a in self.s.asks.live()], ["b1", "b2"])

    def test_answer_records_the_owner_choice_once(self) -> None:
        self.raise_ask("b1")
        ans = AskAnswer(action="rerun", text="go", t=S.T + 9, by="denis")  # pyrefly: ignore[unexpected-keyword]
        done = self.s.asks.answer("b1", ans)
        self.assertEqual((done.status, done.answer, done.answered), (AskStatus.ANSWERED, ans, S.T + 9))
        self.assertEqual(self.s.asks.of("b1").read(), done)
        self.assertIsNone(self.s.asks.answer("b1", ans))  # already answered
        self.assertIsNone(self.s.asks.answer("nope", ans))

    def test_withdraw_only_a_live_ask(self) -> None:
        self.raise_ask("b1")
        self.assertTrue(self.s.asks.withdraw("b1"))
        self.assertEqual(self.s.asks.of("b1").read().status, AskStatus.WITHDRAWN)
        self.assertFalse(self.s.asks.withdraw("b1"))


class CheckpointContract(Base):
    def test_a_full_checkpoint_round_trips(self) -> None:
        self.s.checkpoints.of("tl-1").write(CK)
        self.assertEqual(self.s.checkpoints.of("tl-1").read(), CK)

    def test_close_and_open_beads(self) -> None:
        self.s.checkpoints.of("tl-1").write(CK)
        self.s.checkpoints.of("tl-2").write(dataclasses.replace(CK, bead="tl-2"))
        self.assertEqual(self.s.checkpoints.open_beads(), ["tl-1", "tl-2"])
        self.assertTrue(self.s.checkpoints.close("tl-1").closed)
        self.assertEqual(self.s.checkpoints.open_beads(), ["tl-2"])
        self.assertIsNone(self.s.checkpoints.close("nope"))

    def test_unfiled_follow_ups_are_kept_beside_the_filed_ones(self) -> None:
        self.s.checkpoints.of("tl-1").write(dataclasses.replace(CK, unfiled=[]))
        self.s.checkpoints.add_unfiled("tl-1", [Unfiled(title="t", why="lint")], ["f1", "f2"])  # pyrefly: ignore[unexpected-keyword]
        got = self.s.checkpoints.of("tl-1").read()
        self.assertEqual((got.filed, [u.title for u in got.unfiled]), (["f1", "f2"], ["t"]))
        self.s.checkpoints.of("tl-1").delete()
        self.assertEqual(self.s.checkpoints.docs.keys(), [])
        self.assertIsNone(self.s.checkpoints.add_unfiled("tl-1", [], []))


class LogContract(Base):
    def logs(self) -> list[tuple[Any, list[Any]]]:
        return [(self.s.run_log("r1"), list(S.LOG.values())), (self.s.events, list(S.EVENTS.values())),
                (self.s.traces, [S.TRACE, dataclasses.replace(S.TRACE, bead="tl-2")])]

    def test_append_returns_offsets_and_reading_from_a_cursor_gives_only_the_new(self) -> None:
        for log, recs in self.logs():
            with self.subTest(type(recs[0]).__name__):
                offs = [log.append(r) for r in recs]
                page = log.read_from(0)
                self.assertEqual([i.rec for i in page.items], recs)
                self.assertEqual([i.start for i in page.items], offs)
                self.assertEqual(offs[0], 0)
                log.append(recs[0])
                again = log.read_from(page.cursor)
                self.assertEqual([i.rec for i in again.items], [recs[0]])
                self.assertEqual(again.cursor, log.read_from(0).cursor)

    def test_limit_and_tail(self) -> None:
        log, recs = self.logs()[0]
        for r in recs:
            log.append(r)
        first = log.read_from(0, limit=2)
        self.assertEqual([i.rec for i in first.items], recs[:2])
        self.assertEqual([i.rec for i in log.read_from(first.cursor).items], recs[2:])
        self.assertEqual([i.rec for i in log.tail(3).items], recs[-3:])
        before = log.tail(3).items[0].start
        self.assertEqual([i.rec for i in log.tail(2, before).items], recs[-5:-3])
        self.assertEqual(log.tail(0).items, [])

    def test_a_torn_last_line_waits_and_is_whole_once_finished(self) -> None:
        log, recs = self.logs()[0]
        log.append(recs[0])
        line = (__import__("json").dumps(codec.to_json(recs[1]), ensure_ascii=False, separators=(", ", ": ")) + "\n").encode()
        self.rig.tear(log, line[:20])
        page = log.read_from(0)
        self.assertEqual([i.rec for i in page.items], [recs[0]])
        self.assertEqual(page.cursor, page.items[0].end)  # the cursor stays before the torn line
        self.rig.tear(log, line[20:])
        self.assertEqual([i.rec for i in log.read_from(page.cursor).items], [recs[1]])

    def test_a_complete_line_of_another_family_or_version_is_skipped_and_counted(self) -> None:
        log, recs = self.logs()[0]
        log.append(recs[0])
        self.rig.tear(log, b'{"v": 99, "kind": "note", "t": 1.0, "text": "x"}\nnot json\n[1]\n{"kind": "mystery"}\n')
        log.append(recs[1])
        page = log.read_from(0)
        self.assertEqual([i.rec for i in page.items], [recs[0], recs[1]])
        self.assertEqual(page.skipped, 2)  # the two JSON objects the family refuses; "not json" and "[1]" never become entries

    def test_two_runs_have_two_logs(self) -> None:
        self.s.run_log("a").append(S.LOG["note"])
        self.assertEqual(self.s.run_log("b").read_from(0).items, [])
        self.assertEqual(len(self.s.run_log("a").read_from(0).items), 1)
        self.assertEqual(self.s.events.read_from(0).items, [])


class LockContract(Base):
    W = LockWhat.LAND

    def test_hold_names_the_holder_and_free_means_none(self) -> None:
        self.assertIsNone(self.s.locks.holder(self.W, "r"))
        with self.s.locks.hold(self.W, "r", "tl-1 landing") as rec:
            self.assertEqual((rec.holder, rec.what, rec.pid), ("tl-1 landing", self.W, os.getpid()))
            self.assertEqual(self.s.locks.holder(self.W, "r").holder, "tl-1 landing")
            self.assertIsNone(self.s.locks.holder(self.W, "other"))
            self.assertIsNone(self.s.locks.holder(LockWhat.REVIEW, "r"))
        self.assertIsNone(self.s.locks.holder(self.W, "r"))

    def test_a_second_taker_times_out_and_is_told_who_holds(self) -> None:
        seen: list[Any] = []
        with self.s.locks.hold(self.W, "r", "first"):
            t0 = time.monotonic()
            with self.assertRaises(LockTimeout) as cm:
                with self.s.locks.hold(self.W, "r", "second", timeout=0.2, waiting=seen.append):
                    self.fail("got a held lock")
            self.assertGreaterEqual(time.monotonic() - t0, 0.15)
        self.assertEqual(cm.exception.holder.holder, "first")
        self.assertEqual([h.holder for h in seen], ["first"])  # told once, before it waited
        with self.s.locks.hold(self.W, "r", "third", timeout=0.2):
            pass  # the lock is free again

    def test_a_waiter_gets_the_lock_when_the_holder_leaves_and_an_exception_releases(self) -> None:
        got: list[str] = []

        def waiter() -> None:
            with self.s.locks.hold(self.W, "r", "waiter", timeout=5):
                got.append("waiter")

        with self.assertRaises(RuntimeError):
            with self.s.locks.hold(self.W, "r", "first"):
                t = threading.Thread(target=waiter)
                t.start()
                time.sleep(0.1)
                self.assertEqual(got, [])
                raise RuntimeError("holder fails")
        t.join(5)
        self.assertEqual(got, ["waiter"])

    def test_only_one_thread_is_inside_at_a_time(self) -> None:
        inside, worst, hits = [0], [0], [0]

        def work() -> None:
            for _ in range(5):
                with self.s.locks.hold(self.W, "r", "t", timeout=10):
                    inside[0] += 1
                    worst[0] = max(worst[0], inside[0])
                    hits[0] += 1
                    time.sleep(0.002)
                    inside[0] -= 1

        ts = [threading.Thread(target=work) for _ in range(4)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual((worst[0], hits[0]), (1, 20))

    def test_a_lock_whose_recorded_holder_is_dead_is_broken(self) -> None:
        self.rig.plant_lock(self.W, "r", "ghost", dead_pid())
        with self.s.locks.hold(self.W, "r", "me", timeout=3) as rec:
            self.assertEqual(rec.holder, "me")
            self.assertEqual(self.s.locks.holder(self.W, "r").holder, "me")

    def test_a_lock_whose_recorded_holder_is_alive_is_not_broken(self) -> None:
        self.rig.plant_lock(self.W, "r", "other", os.getpid())
        self.assertEqual(self.s.locks.holder(self.W, "r").holder, "other")
        with self.assertRaises(LockTimeout):
            with self.s.locks.hold(self.W, "r", "me", timeout=0.3):
                self.fail("took a live lock")


class TicketContract(Base):
    def test_numbers_grow_past_the_live_ones_and_the_line_is_priority_then_arrival(self) -> None:
        t = self.s.tickets
        a = t.take("k", "slot", 2, pid=os.getpid(), now=S.T)
        b = t.take("k", "slot", 0, pid=os.getpid(), now=S.T + 1, pid_start=S.T)
        c = t.take("k", "slot", 2, pid=os.getpid(), now=S.T + 2)
        self.assertEqual((a.seq, b.seq, c.seq), (1, 2, 3))
        self.assertEqual([x.seq for x in t.line("k")], [2, 1, 3])
        self.assertEqual(t.line("k")[0], b)
        t.drop("k", 1)
        self.assertEqual(t.take("k", "slot", 2, pid=os.getpid(), now=S.T).seq, 4)
        self.assertEqual(t.line("other"), [])

    def test_a_dead_waiter_drops_out_of_the_line(self) -> None:
        t = self.s.tickets
        t.take("k", "dead", 0, pid=dead_pid(), now=S.T)
        live = t.take("k", "live", 5, pid=os.getpid(), now=S.T)
        self.assertEqual([x.seq for x in t.line("k")], [live.seq])
        t.drop("k", live.seq)
        t.drop("k", live.seq)
        self.assertEqual(t.line("k"), [])
