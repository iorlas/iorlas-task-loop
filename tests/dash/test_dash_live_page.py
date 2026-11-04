"""GET /api/live: the contract's LivePage over the one LiveRun reader: typed lines, the byte-offset cursor, the run-liveness state."""
import json
import sys
import tempfile
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashes import make_dash
from support.factory_index import ingest
from support.logs import typed
from support.runs import manifest

from taskloop.contracts import wire
from taskloop.contracts.dash import LivePage
from taskloop.contracts.ids import loop_key
from taskloop.contracts.run import RunState
from taskloop_dash.api import live

BEAD, RUN = "tl-live.1", "tl-live.1-20261026-100000"
T = 1793000000.0


def put(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class LivePageApi(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = T + 30
        self.dash = make_dash(config=self.tmp.name, clock=lambda: self.now)
        cfg = self.dash.env.config
        self.bundle = manifest(cfg, RUN, BEAD, T)
        self.log, self.lf = self.bundle.log, cfg.live_dir(RUN) / "01-write.jsonl"
        put(self.log, [typed("run_start", T, run_id=RUN, bead=BEAD, worktree=""), typed("beat", T + 1),
                       typed("step_start", T + 2, id="n1", step="write", text="write: x"), typed("beat", T + 3),
                       typed("cmd_start", T + 4, id="m1", text="git fetch -q origin"), typed("cmd_end", T + 5, id="m1", exit=0)])
        put(self.lf, [{"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "pid": 1},
                      {"t": T + 7, "k": "msg", "text": "reading the plan"},
                      {"t": T + 8, "k": "tool_start", "id": "t1", "text": "Read src/x.py"},
                      {"t": T + 9, "k": "cmd_start", "id": "1", "text": "pytest -q"},
                      {"t": T + 10, "k": "cmd_end", "id": "1", "exit": 1, "secs": 2.0, "out": "a\nFAILED test_x\n"}])

    def get(self, since="", wait="0"):
        ingest(self.dash.env.config, self.now)
        code, body = self.dash.live.page(loop_key("/repo"), BEAD, since, wait)
        assert code == 200
        return wire.load(LivePage, body)  # strict: an unknown or missing key raises

    def test_first_load_is_typed_lines_in_time_order_without_beats(self):
        page = self.get()
        assert page.state == "live"
        assert (
            [ln.text for ln in page.lines]
            == ["> write: x", "$ git fetch -q origin", "exit 0 (0s)", "worker codex CODEX gpt-x", "reading the plan",
                          "tool Read src/x.py", "$ pytest -q", "exit 1 (2s)", "a", "FAILED test_x"]
        )
        assert [ln.t for ln in page.lines] == sorted(ln.t for ln in page.lines)
        tones = {ln.text: ln.tone for ln in page.lines}
        assert (tones["exit 0 (0s)"], tones["exit 1 (2s)"], tones["FAILED test_x"], tones["reading the plan"]) == ("ok", "err", "dim", "")
        assert [(t.name, t.arg) for t in page.tools] == [("Read src/x.py", "")]  # delegate types the tool's text only

    def test_an_unverified_check_reads_apart_from_passed_and_failed(self):
        put(self.log, [typed("check_end", T + 5.5, id="c1", exit=0, status="passed"),
                       typed("check_end", T + 5.6, id="c2", exit=86, status="unverified"),
                       typed("check_end", T + 5.7, id="c3", exit=1, status="failed")])
        tones = {ln.text: ln.tone for ln in self.get().lines if ln.text.startswith("check ")}
        assert tones == {"check passed": "ok", "check unverified": "warn", "check failed": "err"}

    def test_the_cursor_round_trips_and_a_beat_is_no_line(self):
        first = self.get()
        assert live.decode(first.cursor) == self.dash.live.live_run(self.bundle.run).offsets()
        assert self.get(first.cursor).lines == []
        put(self.log, [typed("beat", T + 20)])
        quiet = self.get(first.cursor)
        assert (quiet.lines, quiet.cursor == first.cursor) == ([], False)  # log cursor advances past Beats
        put(self.lf, [{"t": T + 21, "k": "msg", "text": "done"}, {"t": T + 22, "k": "stall", "secs": 61}])
        more = self.get(quiet.cursor)
        assert [(ln.text, ln.tone) for ln in more.lines] == [("done", ""), ("no output for 61s", "err")]
        assert self.get(more.cursor).lines == []

    def test_a_garbage_cursor_is_a_first_load(self):
        assert len(self.get("not-a-cursor").lines) == len(self.get().lines)

    def test_a_long_poll_with_nothing_new_returns_when_it_runs_out(self):
        first = self.get()
        assert self.get(first.cursor, wait="0").lines == []

    def test_state_is_the_runs_recorded_state_whatever_the_clock_says(self):
        self.now = T + 99_999  # no record for a day: the log's silence says nothing
        assert self.get().state == "live"
        self.bundle = manifest(self.dash.env.config, RUN, BEAD, T, state=RunState.LOST)
        assert self.get().state == "lost"
        self.bundle = manifest(self.dash.env.config, RUN, BEAD, T, state=RunState.DONE)
        assert self.get().state == "ended"

    def test_no_run_is_404_and_an_odd_id_is_never_read(self):
        ingest(self.dash.env.config, self.now)
        assert self.dash.live.page(loop_key("/repo"), "nope-1")[0] == 404
        assert self.dash.live.page(loop_key("/repo"), "--x")[0] == 404
