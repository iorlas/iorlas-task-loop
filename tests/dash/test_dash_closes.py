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
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import RunId
from taskloop.contracts.kinds import ASKS, Kind
from taskloop.contracts.log import Close
from taskloop.contracts.trace import RunTrace, Stats
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
from taskloop_dash.env import Env
from taskloop_dash.readers.records import Records


def close_of(kind: Kind) -> Close:
    spec = AskSpec.__new__(AskSpec) if kind in ASKS else None  # the word needs no spec's content
    word = oc.make(kind, "x", spec=spec).word
    return Close(t=T, outcome=word, why_code=why_code(kind.value, word), why="x")


def trace(run: str, outcome: Outcome, ended: float, replans: int = 0) -> RunTrace:
    return RunTrace(run=must(RunId.of(run)), bead="g-1", repo_url="u", worktree="/w", branch="b", coordinator_session="s",
                    started=ended - 60, ended=ended, outcome=outcome, why="", sha="", stats=Stats(replans=replans))


class Traces(unittest.TestCase):
    def test_traces_of_another_version_are_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            rows = [wire.dump(trace("g-1-20261015-100000", Outcome.LANDED, T + 100, replans=2)),
                    wire.dump(trace("g-1-20261015-110000", Outcome.FAILED, T + 200)),
                    dict(wire.dump(trace("g-1-20261015-120000", Outcome.LANDED, T + 300)), v=1), {"outcome": "landed", "run": "r-4"}]
            (cfg / "traces.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            env = Env(config=cfg, home=cfg, clock=lambda: T, version="v")
            book = Records(env).traces()
            self.assertEqual((sorted(book.runs), book.skipped), (["g-1-20261015-100000", "g-1-20261015-110000"], 3))


if __name__ == "__main__":
    unittest.main()
