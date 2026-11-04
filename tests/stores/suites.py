"""One suite per store family. Each is a mixin over `make_rig()`; test_contract.py runs it against the file-backed stores and
against the in-memory ones, so a fake cannot drift from the real thing without a test going red."""
import os
import threading
import time
from typing import Any, cast

import pytest
from contracts import samples as S
from rigs import dead_pid
from support.case import Case
from support.narrow import must

from taskloop.contracts import wire
from taskloop.contracts.ask import Ask, AskAnswer
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.enums import AskStatus, LockWhat
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.loop import LoopCommand, LoopState, Rest

CK = cast(Checkpoint, S.OTHERS["Checkpoint"])


class Base(Case):
    def make_rig(self) -> Any:
        raise NotImplementedError

    def setup_method(self) -> None:
        self.rig = self.make_rig()
        self.addCleanup(self.rig.close)
        self.s = self.rig.stores


class DocContract(Base):
    def test_a_missing_document_reads_as_none_and_a_write_reads_back_equal(self) -> None:
        doc = self.s.loop_state("k")
        assert doc.get() is None
        doc.write(S.other(LoopState))
        assert doc.get() == S.other(LoopState)
        assert self.s.loop_state("k").get() == S.other(LoopState)  # a new handle sees it
        assert self.s.loop_state("other").get() is None

    def test_a_write_replaces_whole_and_delete_removes(self) -> None:
        doc = self.s.loop_rest("k")
        doc.write(S.other(Rest))
        doc.write(S.other(Rest).replace(beads={"b-2": 7.0}))
        assert doc.get().beads == {"b-2": 7.0}
        doc.delete()
        assert doc.get() is None
        doc.delete()  # deleting nothing is fine

    def test_a_document_of_another_version_or_shape_reads_as_absent(self) -> None:
        doc = self.s.loop_command("k")
        self.rig.poison(doc, {"v": 99, "action": "resume", "by": "x", "t": 1.0})
        assert doc.get() is None
        self.rig.poison(doc, {"v": 1, "action": "dance", "by": "x", "t": 1.0})
        assert doc.get() is None
        doc.write(S.other(LoopCommand))
        assert doc.get() == S.other(LoopCommand)


class AskContract(Base):
    def raise_ask(self, bead: str, status: AskStatus = AskStatus.OPEN, t: float = S.T) -> Ask:
        a = S.ASK.replace(
            bead=bead, id=bead + "-1", status=status, answer=None, answered=None, consumed=None, t=t)
        self.s.asks.of(bead).write(a)
        return a

    def test_live_lists_open_and_parked_asks_oldest_first(self) -> None:
        self.raise_ask("b2", t=S.T + 5)
        self.raise_ask("b1", AskStatus.PARKED, t=S.T)
        self.raise_ask("b3", AskStatus.WITHDRAWN)
        assert [a.bead for a in self.s.asks.live()] == ["b1", "b2"]

    def test_answer_records_the_owner_choice_once(self) -> None:
        self.raise_ask("b1")
        ans = AskAnswer(action="rerun", text="go", t=S.T + 9, by="denis")  # pyrefly: ignore[unexpected-keyword]
        done, why = self.s.asks.answer("b1", "b1-1", ans)
        assert (why, done.status, done.answer, done.answered) == ("", AskStatus.ANSWERED, ans, S.T + 9)
        assert self.s.asks.of("b1").get() == done
        assert self.s.asks.answer("b1", "b1-1", ans)[1] == "answered"  # the first answer wins
        assert self.s.asks.answer("nope", "nope-1", ans) == (None, "gone")
        assert self.s.asks.answer("b1", "b1-0", ans)[1] == "superseded"

    def test_amend_replaces_an_answer_no_run_used_and_consume_ends_it(self) -> None:
        self.raise_ask("b1")
        one = AskAnswer(action="text", text="a", t=S.T + 1, by="d")  # pyrefly: ignore[unexpected-keyword]
        two = AskAnswer(action="text", text="b", t=S.T + 2, by="d")  # pyrefly: ignore[unexpected-keyword]
        self.s.asks.answer("b1", "b1-1", one)
        assert self.s.asks.amend("b1", "b1-1", two)[0].answer == two
        used = self.s.asks.consume("b1", S.T + 5)
        assert (used.consumed, used.answer) == (S.T + 5, two)
        assert self.s.asks.consume("b1", S.T + 6) is None  # used once
        assert self.s.asks.amend("b1", "b1-1", one)[1] == "consumed"

    def test_withdraw_only_an_ask_no_run_used(self) -> None:
        self.raise_ask("b1")
        done, why = self.s.asks.withdraw("b1", "b1-1", "no longer", S.T + 1)
        assert (why, done.status, done.closed_why) == ("", AskStatus.WITHDRAWN, "no longer")
        assert self.s.asks.withdraw("b1", "b1-1", "again", S.T + 2)[1] == ""  # already withdrawn: fine
        self.raise_ask("b2")
        self.s.asks.consume("b2", S.T + 1, unanswered=True)
        assert self.s.asks.withdraw("b2", "b2-1", "x", S.T + 2)[1] == "consumed"

    def test_close_and_park_touch_only_the_ask_they_read(self) -> None:
        self.raise_ask("b1")
        assert not self.s.asks.close("b1", "b1-0", "gone")
        assert self.s.asks.park("b1", "b1-1")
        assert not self.s.asks.park("b1", "b1-1")  # parked already
        assert self.s.asks.close("b1", "b1-1", "the bead is closed")
        assert self.s.asks.get("b1").closed_why == "the bead is closed"


class CheckpointContract(Base):
    def test_a_full_checkpoint_round_trips(self) -> None:
        self.s.checkpoints.of("tl-1").write(CK)
        assert self.s.checkpoints.of("tl-1").get() == CK

    def test_open_beads_leaves_out_a_closed_one(self) -> None:
        self.s.checkpoints.of("tl-1").write(CK)
        self.s.checkpoints.of("tl-2").write(CK.replace(bead="tl-2"))
        assert self.s.checkpoints.open_beads() == ["tl-1", "tl-2"]
        self.s.checkpoints.of("tl-1").write(CK.replace(closed=True))
        assert self.s.checkpoints.open_beads() == ["tl-2"]

    def test_delete_removes_the_record(self) -> None:
        self.s.checkpoints.of("tl-1").write(CK)
        self.s.checkpoints.of("tl-1").delete()
        assert self.s.checkpoints.docs.keys() == []


class LogContract(Base):
    def logs(self) -> list[tuple[Any, list[Any]]]:
        return [(self.s.run_log("r1"), list(S.LOG.values())), (self.s.events, list(S.EVENTS.values())),
                (self.s.traces, [S.TRACE, S.TRACE.replace(bead="tl-2")])]

    def test_append_returns_offsets_and_reading_from_a_cursor_gives_only_the_new(self) -> None:
        for log, recs in self.logs():
            with self.subTest(type(recs[0]).__name__):
                offs = [log.append(r) for r in recs]
                page = log.read_from(0)
                assert [i.rec for i in page.items] == recs
                assert [i.start for i in page.items] == offs
                assert offs[0] == 0
                log.append(recs[0])
                again = log.read_from(page.cursor)
                assert [i.rec for i in again.items] == [recs[0]]
                assert again.cursor == log.read_from(0).cursor

    def test_limit_and_tail(self) -> None:
        log, recs = self.logs()[0]
        for r in recs:
            log.append(r)
        first = log.read_from(0, limit=2)
        assert [i.rec for i in first.items] == recs[:2]
        assert [i.rec for i in log.read_from(first.cursor).items] == recs[2:]
        assert [i.rec for i in log.tail(3).items] == recs[-3:]
        before = log.tail(3).items[0].start
        assert [i.rec for i in log.tail(2, before).items] == recs[-5:-3]
        assert log.tail(0).items == []

    def test_a_torn_last_line_waits_and_is_whole_once_finished(self) -> None:
        log, recs = self.logs()[0]
        log.append(recs[0])
        line = (__import__("json").dumps(wire.dump(recs[1]), ensure_ascii=False, separators=(", ", ": ")) + "\n").encode()
        self.rig.tear(log, line[:20])
        page = log.read_from(0)
        assert [i.rec for i in page.items] == [recs[0]]
        assert page.cursor == page.items[0].end  # the cursor stays before the torn line
        self.rig.tear(log, line[20:])
        assert [i.rec for i in log.read_from(page.cursor).items] == [recs[1]]

    def test_a_complete_line_of_another_family_or_version_is_skipped_and_counted(self) -> None:
        log, recs = self.logs()[0]
        log.append(recs[0])
        self.rig.tear(log, b'{"v": 99, "kind": "note", "t": 1.0, "text": "x"}\nnot json\n[1]\n{"kind": "mystery"}\n')
        log.append(recs[1])
        page = log.read_from(0)
        assert [i.rec for i in page.items] == [recs[0], recs[1]]
        assert page.skipped == 2  # the two JSON objects the family refuses; "not json" and "[1]" never become entries

    def test_two_runs_have_two_logs(self) -> None:
        self.s.run_log("a").append(S.LOG["note"])
        assert self.s.run_log("b").read_from(0).items == []
        assert len(self.s.run_log("a").read_from(0).items) == 1
        assert self.s.events.read_from(0).items == []


class LockContract(Base):
    W = LockWhat.LAND

    def test_hold_names_the_holder_and_free_means_none(self) -> None:
        assert self.s.locks.holder(self.W, "r") is None
        with self.s.locks.hold(self.W, "r", "tl-1 landing") as rec:
            assert (rec.holder, rec.what, rec.pid) == ("tl-1 landing", self.W, os.getpid())
            assert self.s.locks.holder(self.W, "r").holder == "tl-1 landing"
            assert self.s.locks.holder(self.W, "other") is None
            assert self.s.locks.holder(LockWhat.REVIEW, "r") is None
        assert self.s.locks.holder(self.W, "r") is None

    def test_a_second_taker_times_out_and_is_told_who_holds(self) -> None:
        seen: list[Any] = []
        with self.s.locks.hold(self.W, "r", "first"):
            t0 = time.monotonic()
            with pytest.raises(LockTimeout) as cm, self.s.locks.hold(self.W, "r", "second", timeout=0.2, waiting=seen.append):
                pytest.fail("got a held lock")
            assert time.monotonic() - t0 >= 0.15
        assert must(cm.value.holder).holder == "first"
        assert [h.holder for h in seen] == ["first"]  # told once, before it waited
        with self.s.locks.hold(self.W, "r", "third", timeout=0.2):
            pass  # the lock is free again

    def test_a_waiter_gets_the_lock_when_the_holder_leaves_and_an_exception_releases(self) -> None:
        got: list[str] = []

        def waiter() -> None:
            with self.s.locks.hold(self.W, "r", "waiter", timeout=5):
                got.append("waiter")

        with pytest.raises(RuntimeError), self.s.locks.hold(self.W, "r", "first"):
            t = threading.Thread(target=waiter)
            t.start()
            time.sleep(0.1)
            assert got == []
            raise RuntimeError("holder fails")
        t.join(5)
        assert got == ["waiter"]

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
        assert (worst[0], hits[0]) == (1, 20)

    def test_a_lock_whose_recorded_holder_is_alive_is_not_broken(self) -> None:
        self.rig.plant_lock(self.W, "r", "other", os.getpid())
        assert self.s.locks.holder(self.W, "r").holder == "other"
        with pytest.raises(LockTimeout), self.s.locks.hold(self.W, "r", "me", timeout=0.3):
            pytest.fail("took a live lock")


class TicketContract(Base):
    def test_numbers_grow_past_the_live_ones_and_the_line_is_priority_then_arrival(self) -> None:
        t = self.s.tickets
        a = t.take("k", "slot", 2, pid=os.getpid(), now=S.T)
        b = t.take("k", "slot", 0, pid=os.getpid(), now=S.T + 1, pid_start=S.T)
        c = t.take("k", "slot", 2, pid=os.getpid(), now=S.T + 2)
        assert (a.seq, b.seq, c.seq) == (1, 2, 3)
        assert [x.seq for x in t.line("k")] == [2, 1, 3]
        assert t.line("k")[0] == b
        t.drop("k", 1)
        assert t.take("k", "slot", 2, pid=os.getpid(), now=S.T).seq == 4
        assert t.line("other") == []

    def test_numbers_keep_growing_after_the_line_has_emptied(self) -> None:
        t = self.s.tickets
        first = t.take("k", "slot", 2, pid=os.getpid(), now=S.T)
        t.drop("k", first.seq)
        assert t.take("k", "slot", 2, pid=os.getpid(), now=S.T).seq > first.seq

    def test_a_dead_waiter_drops_out_of_the_line(self) -> None:
        t = self.s.tickets
        t.take("k", "dead", 0, pid=dead_pid(), now=S.T)
        live = t.take("k", "live", 5, pid=os.getpid(), now=S.T)
        assert [x.seq for x in t.line("k")] == [live.seq]
        t.drop("k", live.seq)
        t.drop("k", live.seq)
        assert t.line("k") == []
