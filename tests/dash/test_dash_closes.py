"""A stored run end read for the dashboard: the Close of every Kind the engine writes names the Fault of that Kind (the two tables,
trace.WHY_CODE and readers.closes.BY_CODE, agree); a close this version cannot have written is unread; traces of another version
are skipped and counted."""

import json
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import T
from support.narrow import must

from taskloop_dash.env import Env
from taskloop_dash.readers.records import Records
from tlkernel import wire
from tlkernel.enums import Outcome
from tlkernel.ids import RunId
from tlkernel.trace import RunTrace, Stats


def trace(run: str, outcome: Outcome, ended: float, replans: int = 0) -> RunTrace:
    return RunTrace(run=must(RunId.of(run)), bead="g-1", repo_url="u", worktree="/w", branch="b", coordinator_session="s",
                    started=ended - 60, ended=ended, outcome=outcome, why="", sha="", stats=Stats(replans=replans))


class Traces(Case):
    def test_traces_of_another_version_are_skipped_and_counted(self):
        with TemporaryDirectory() as d:
            cfg = Path(d)
            rows = [wire.dump(trace("01KBN6Z0M4R5E8YQ2T7C9W3XA1", Outcome.LANDED, T + 100, replans=2)),
                    wire.dump(trace("01KBN6Z0M4R5E8YQ2T7C9W3XA2", Outcome.FAILED, T + 200)),
                    dict(wire.dump(trace("01KBN6Z0M4R5E8YQ2T7C9W3XA3", Outcome.LANDED, T + 300)), v=1), {"outcome": "landed", "run": "r-4"}]
            (cfg / "traces.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            env = Env(config=cfg, home=cfg, clock=lambda: T, version="v")
            book = Records(env).traces()
            assert (sorted(book.runs), book.skipped) == (["01KBN6Z0M4R5E8YQ2T7C9W3XA1", "01KBN6Z0M4R5E8YQ2T7C9W3XA2"], 3)
