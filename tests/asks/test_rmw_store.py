"""Read-modify-write stores (RMWSTORE): two writers to one ask document never lose an answer, a consume of an ask nobody answered is
refused unless it says so, and a line appended while a log is pruned survives (usage history and the events trail)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from contracts import samples as S
from support import homes
from support.narrow import must
from support.who import who

from taskloop.app.track import trail
from taskloop.contracts.ask import AskAnswer
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import LaneStatus, StatusSnapshot, WindowStatus
from taskloop.contracts.stores import AskStore, UsageHistory
from taskloop.contracts.usage import USAGE_KEEP_S

T = S.T


def answer(text: str) -> AskAnswer:
    return AskAnswer(action="text", text=text, t=T + 1, by="d")  # pyrefly: ignore[unexpected-keyword]


class SlowDocs:
    """The ask documents, each read followed by a pause: the window a lock-less read-modify-write loses an update in."""

    def __init__(self, inner):
        self.inner = inner

    def of(self, key):
        doc = self.inner.of(key)
        read = doc.read

        def slow():
            got = read()
            time.sleep(0.05)
            return got
        return mock.Mock(read=slow, write=doc.write, delete=doc.delete, path=doc.path)

    def keys(self):
        return self.inner.keys()


class Asks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(tmp.name)
        AskStore.at(self.cfg).file(S.ASK.replace(status=AskStatus.OPEN, answer=None, answered=None, consumed=None))

    def store(self) -> AskStore:
        st = AskStore.at(self.cfg)  # its own descriptors, as a second process has
        st.docs = SlowDocs(st.docs)
        return st

    def race(self, *fns) -> list:
        out: list = [None] * len(fns)

        def run(i, fn):
            out[i] = fn()
        ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        return out

    def test_two_answers_to_one_ask_keep_exactly_the_first(self):
        a, b = self.store(), self.store()
        t1 = BeadId("tl-1")
        got: list = self.race(lambda: a.answer(t1, "tl-1-1", answer("A")), lambda: b.answer(t1, "tl-1-1", answer("B")))
        self.assertEqual(sorted(why for _, why in got), ["", "answered"])
        winner = next(done for done, why in got if not why)
        self.assertEqual(must(AskStore.at(self.cfg).get(BeadId("tl-1"))).answer, must(winner).answer)

    def test_a_run_that_goes_on_never_overwrites_an_answer_filed_meanwhile(self):
        a, b = self.store(), self.store()
        self.race(lambda: a.answer(BeadId("tl-1"), "tl-1-1", answer("A")), lambda: b.consume(BeadId("tl-1"), T + 5, unanswered=True))
        got = must(AskStore.at(self.cfg).get(BeadId("tl-1")))
        if got.consumed is not None and got.answer is None:  # the run went first: the answer must have been refused
            self.assertEqual(AskStore.at(self.cfg).answer(BeadId("tl-1"), "tl-1-1", answer("A"))[1], "consumed")
        else:
            self.assertEqual(must(got.answer).text, "A")

    def test_consume_of_an_ask_nobody_answered_is_refused(self):
        st = AskStore.at(self.cfg)
        self.assertIsNone(st.consume(BeadId("tl-1"), T + 5))
        self.assertEqual(must(st.get(BeadId("tl-1"))).status, AskStatus.OPEN)
        self.assertIsNone(must(st.get(BeadId("tl-1"))).consumed)
        self.assertEqual(must(st.consume(BeadId("tl-1"), T + 6, unanswered=True)).consumed, T + 6)


def snap(at):
    return StatusSnapshot(at=at, lanes=[LaneStatus(
        id="A", label="Claude", family="claude", kind="subscription", model="m", state="ready", five=None, week=None, unlock_at=at + 600,
        out=False, out_until=None, windows=[WindowStatus(name="whatever", used_pct=10.0, resets_at=at + 3600)])])


def during(real, fn):
    """`real` wrapped: before it runs, `fn` starts on a thread (an appender) and gets a moment to try; its thread is returned."""
    started = []

    def wrapped(*a, **k):
        t = threading.Thread(target=fn)
        t.start()
        started.append(t)
        time.sleep(0.3)
        return real(*a, **k)
    return wrapped, started


class Logs(unittest.TestCase):
    def test_a_usage_row_appended_during_prune_survives(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = ConfigDir(tmp.name)
        h = UsageHistory(cfg)
        h.record(snap(T - USAGE_KEEP_S - 5))
        h.record(snap(T))
        wrapped, started = during(UsageHistory.read_from, lambda: UsageHistory(cfg).record(snap(T + 7)))
        with mock.patch.object(UsageHistory, "read_from", wrapped):
            self.assertEqual(h.prune(T), 1)
        for t in started:
            t.join(30)
        self.assertEqual([r.at for r in h.rows()], [T, T + 7])

    def test_an_event_appended_during_prune_survives(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp.name, "CLAUDE_CODE_SESSION_ID": "abcdef12-3456"}):
            f = ConfigDir(Path(tmp.name) / "task-loop").events()
            f.parent.mkdir(parents=True)
            f.write_text((json.dumps({"t": 0, "kind": "old"}) + "\n") * 120000)
            wrapped, started = during(os.replace, lambda: trail.event(who(), "stage", "tl-1", repo="/r/x"))
            with mock.patch("os.replace", wrapped):
                trail.prune_events(homes.cfg())
            for t in started:
                t.join(30)
            self.assertEqual([json.loads(ln)["kind"] for ln in f.read_text().splitlines()], ["stage"])
