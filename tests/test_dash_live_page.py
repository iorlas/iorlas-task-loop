"""GET /api/live: the contract's LivePage over the one LiveRun reader: typed lines, the byte-offset cursor, the run-liveness state."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401
from support.dashes import make_dash
from support.logs import typed

from taskloop.contracts import wire
from taskloop.contracts.dash import LivePage
from taskloop.contracts.runlife import CRASHED_AFTER
from taskloop_dash.api import live

BEAD, RUN = "tl-live.1", "tl-live.1-20261026-100000"
T = 1793000000.0


def put(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class LivePageApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = T + 30
        self.dash = make_dash(config=self.tmp.name, clock=lambda: self.now)
        cfg = self.dash.env.config
        self.log, self.lf = cfg.engine_log(RUN), cfg.live_dir(RUN) / "01-write.jsonl"
        put(self.log, [typed("run_start", T, run=RUN, bead=BEAD, worktree=""), typed("beat", T + 1),
                       typed("step_start", T + 2, id="n1", step="write", text="write: x"), typed("beat", T + 3),
                       typed("cmd_start", T + 4, id="m1", text="git fetch -q origin"), typed("cmd_end", T + 5, id="m1", exit=0)])
        put(self.lf, [{"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "pid": 1},
                      {"t": T + 7, "k": "msg", "text": "reading the plan"},
                      {"t": T + 8, "k": "tool_start", "id": "t1", "text": "Read src/x.py"},
                      {"t": T + 9, "k": "cmd_start", "id": "1", "text": "pytest -q"},
                      {"t": T + 10, "k": "cmd_end", "id": "1", "exit": 1, "secs": 2.0, "out": "a\nFAILED test_x\n"}])

    def get(self, since="", wait="0"):
        code, body = self.dash.live.page(BEAD, since, wait)
        self.assertEqual(code, 200)
        return wire.load(LivePage, body)  # strict: an unknown or missing key raises

    def test_first_load_is_typed_lines_in_time_order_without_beats(self):
        page = self.get()
        self.assertEqual(page.state, "live")
        self.assertEqual([ln.text for ln in page.lines],
                         ["> write: x", "$ git fetch -q origin", "exit 0 (0s)", "worker codex CODEX gpt-x", "reading the plan",
                          "tool Read src/x.py", "$ pytest -q", "exit 1 (2s)", "a", "FAILED test_x"])
        self.assertEqual([ln.t for ln in page.lines], sorted(ln.t for ln in page.lines))
        tones = {ln.text: ln.tone for ln in page.lines}
        self.assertEqual((tones["exit 0 (0s)"], tones["exit 1 (2s)"], tones["FAILED test_x"], tones["reading the plan"]),
                         ("ok", "err", "dim", ""))
        self.assertEqual([(t.name, t.arg) for t in page.tools], [("Read src/x.py", "")])  # delegate types the tool's text only

    def test_the_cursor_round_trips_and_a_beat_is_no_line(self):
        first = self.get()
        self.assertEqual(live.decode(first.cursor), self.dash.live.live_run(str(self.log)).offsets())
        self.assertEqual(self.get(first.cursor).lines, [])
        put(self.log, [typed("beat", T + 20)])
        quiet = self.get(first.cursor)
        self.assertEqual((quiet.lines, quiet.cursor == first.cursor), ([], False))  # the offset moved, nothing to show
        put(self.lf, [{"t": T + 21, "k": "msg", "text": "done"}, {"t": T + 22, "k": "stall", "secs": 61}])
        more = self.get(quiet.cursor)
        self.assertEqual([(ln.text, ln.tone) for ln in more.lines], [("done", ""), ("no output for 61s", "err")])
        self.assertEqual(self.get(more.cursor).lines, [])

    def test_a_garbage_cursor_is_a_first_load(self):
        self.assertEqual(len(self.get("not-a-cursor").lines), len(self.get().lines))

    def test_a_long_poll_with_nothing_new_returns_when_it_runs_out(self):
        first = self.get()
        self.assertEqual(self.get(first.cursor, wait="0").lines, [])

    def test_state_is_the_run_liveness_rule_on_the_clock(self):
        self.assertEqual(self.get().state, "live")
        self.now = T + 5 + CRASHED_AFTER - 1  # the newest engine record is at T + 5
        self.assertEqual(self.get().state, "live")
        self.now = T + 5 + CRASHED_AFTER + 1
        self.assertEqual(self.get().state, "crashed")  # a stale log whose run never closed
        put(self.log, [typed("beat", self.now)])
        self.assertEqual(self.get().state, "live")
        put(self.log, [typed("close", self.now, outcome="done")])
        self.assertEqual(self.get().state, "ended")

    def test_no_run_is_404_and_an_odd_id_is_never_read(self):
        self.assertEqual(self.dash.live.page("nope-1")[0], 404)
        self.assertEqual(self.dash.live.page("--x")[0], 404)


if __name__ == "__main__":
    unittest.main()
