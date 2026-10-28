"""Replay a run record by record: after each append, /api/live and /api/live/overview must tell the same story (Mac saw running=true
with the bead missing from the overview for one poll)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import support.paths  # noqa: E402,F401
from support.logs import typed  # noqa: E402
from taskloop_dash.api.liveview import Live  # noqa: E402
from taskloop_dash.env import Env  # noqa: E402
from taskloop_dash.readers.records import Records  # noqa: E402

BEAD, STAMP, T = "tl-agree.1", "20261026-100000", 1793000000.0


class Agree(unittest.TestCase):
    def test_every_step_live_and_overview_agree(self):
        with tempfile.TemporaryDirectory() as d:
            now = [T]
            env = Env(config=d, home=d, clock=lambda: now[0])
            lanes = mock.Mock()
            lanes.delegate_status.return_value = {"lanes": []}
            live = Live(env, Records(env), lanes)
            live.queue_rows = lambda: []
            log = env.config.engine_log("%s-%s" % (BEAD, STAMP))
            os.makedirs(os.path.dirname(log), exist_ok=True)
            recs = [typed("run_start", T, run="%s-%s" % (BEAD, STAMP), bead=BEAD, worktree=""),
                    typed("step_start", T + 1, id="n1", text="write", step="write"),
                    typed("cmd_start", T + 2, id="m1", text="pytest"),
                    typed("cmd_end", T + 3, id="m1", exit=0),
                    typed("close", T + 4, why="done")]
            import json
            open(log, "w").close()  # the file exists before its first record
            for i, r in enumerate([None] + recs):
                if r is not None:
                    line = json.dumps(r) + "\n"
                    with open(log, "a", encoding="utf-8") as f:
                        f.write(line[:20])  # a half-written record, then the rest
                    self.check(live, i - 0.5)
                    with open(log, "a", encoding="utf-8") as f:
                        f.write(line[20:])
                    now[0] = r["t"] + 0.05
                self.check(live, i)

    def check(self, live, i):
        a = live.api_live(BEAD)
        o = live.api_live_overview()
        listed = [b["bead"] for b in o["beads"]]
        if not a.get("found"):
            return self.assertEqual(listed, [], i)
        if a["running"]:
            self.assertIn(BEAD, listed, "step %s: live running but the overview lacks the bead" % i)
            row = next(b for b in o["beads"] if b["bead"] == BEAD)
            self.assertEqual(row["state"], a["state"]["what"], i)
        else:
            self.assertNotIn(BEAD, listed, i)


class Threaded(unittest.TestCase):
    def test_concurrent_readers_never_double_or_drop_an_event(self):
        import json
        import threading
        from taskloop_dash.api import live
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "task-loop", "engine", "%s-%s.jsonl" % (BEAD, STAMP))
            os.makedirs(os.path.dirname(log))
            open(log, "w").close()
            run, stop = live.LiveRun(log), threading.Event()

            def reader():
                while not stop.is_set():
                    run.refresh()
                    ev = run.events()
                    assert len({e["seq"] for e in ev}) == len(ev), "duplicate"

            ts = [threading.Thread(target=reader) for _ in range(4)]
            [t.start() for t in ts]
            for n in range(300):
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(typed("warn", T + n, text="w")) + "\n")
            stop.set()
            [t.join() for t in ts]
            run.refresh()
            self.assertEqual(len(run.events()), 300)


if __name__ == "__main__":
    unittest.main()
