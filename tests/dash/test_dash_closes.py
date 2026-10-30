"""A stored run end read for the dashboard: the Close of every Kind the engine writes names the Fault of that Kind (the two tables,
trace.WHY_CODE and readers.closes.BY_CODE, agree); a close this version cannot have written is unread; traces of another version
are skipped and counted."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import T
from support.narrow import must

from taskloop.app.run.trace import why_code
from taskloop.contracts import wire
from taskloop.contracts.enums import Outcome, WhyCode
from taskloop.contracts.ids import RunId
from taskloop.contracts.kinds import ASKS, FINISH, Fault, Infra, Kind, Owner, Task, fault_of
from taskloop.contracts.log import Close
from taskloop.contracts.trace import RunTrace, Stats
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
from taskloop_dash.env import Env
from taskloop_dash.readers import closes
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.closes import End


def close_of(kind: Kind) -> Close:
    word = oc.make(kind, "x", spec=AskSpec.__new__(AskSpec) if kind in ASKS else None).word  # the word needs no spec's content
    return Close(t=T, outcome=word, why_code=why_code(kind.value, word), why="x")


class Closes(unittest.TestCase):
    def test_every_kind_reads_back_as_its_own_kind_of_fault(self):
        for kind in (k for k in Kind if k is not Kind.CUT):  # no production code raises CUT
            with self.subTest(kind=kind):
                ended = closes.read(close_of(kind))
                if kind in FINISH:
                    self.assertEqual((must(ended).fault, must(ended).end), (None, End.FINISHED))
                    continue
                fault: Fault = must(must(ended).fault)
                self.assertIs(type(fault), type(must(fault_of(kind))))
                self.assertEqual(must(ended).end, closes.end_of(fault_of(kind)))

    def test_the_kinds_a_view_can_tell_apart_come_back_exactly(self):
        for kind in (*ASKS, Kind.WAIT_ASK, Kind.OWNER_PARK, Kind.PAUSE_LANE, Kind.PAUSE_NETWORK, Kind.PAUSE_KILLED, Kind.FAULT_DENIED):
            with self.subTest(kind=kind):
                self.assertEqual(must(closes.read(close_of(kind))).fault, fault_of(kind))

    def test_a_close_no_version_writes_is_unread(self):
        self.assertIsNone(closes.read(Close(t=T, outcome=Outcome.BLOCKED)))
        self.assertIsNone(closes.read(Close(t=T, outcome=Outcome.FAILED, why_code=WhyCode.HUNG)))
        self.assertEqual(must(closes.read(Close(t=T, outcome=Outcome.LANDED))).end, End.FINISHED)
        self.assertEqual([type(f) for f in (Infra(Kind.CUT), Task(Kind.ASK_STUCK), Owner(Kind.WAIT_ASK))], [Infra, Task, Owner])


def trace(run: str, outcome: Outcome, ended: float, replans: int = 0) -> RunTrace:
    return RunTrace(run=must(RunId.of(run)), bead="g-1", repo_url="u", worktree="/w", branch="b", coordinator_session="s", started=ended - 60,
                    ended=ended, outcome=outcome, why="", sha="", stats=Stats(replans=replans))


class Traces(unittest.TestCase):
    def test_traces_of_another_version_are_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            rows = [wire.dump(trace("g-1-20261015-100000", Outcome.LANDED, T + 100, replans=2)), wire.dump(trace("g-1-20261015-110000", Outcome.FAILED, T + 200)),
                    dict(wire.dump(trace("g-1-20261015-120000", Outcome.LANDED, T + 300)), v=1), {"outcome": "landed", "run": "r-4"}]
            (cfg / "traces.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            env = Env(config=cfg, home=cfg, clock=lambda: T, version="v")
            book = Records(env).traces()
            self.assertEqual((sorted(book.runs), book.skipped), (["g-1-20261015-100000", "g-1-20261015-110000"], 3))


if __name__ == "__main__":
    unittest.main()
