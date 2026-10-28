"""One bead's whole time (tl-9h2): steps, checks, waits and idle as segments with totals; an open step ends now."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.logs import typed, write_log  # noqa: E402
from taskloop_dash.views import segments, timeline  # noqa: E402

T = 1_800_000_000.0


def block(kind, t0, t1, node=1):
    return {"node": node, "kind": kind, "label": kind.title(), "t0": T + t0, "t1": T + t1}


def run(name, t0, t1, blocks, waits=(), outcome="landed"):
    return {"run": name, "started": T + t0, "ended": T + t1, "blocks": blocks, "end": {"outcome": outcome},
            "waits": [{"what": w, "label": "", "t0": T + a, "secs": b, "holder": "x", "in_budget": False} for w, a, b in waits]}


def totals(tl):
    t = tl["totals"]
    return t["work"], t["checks"], t["wait"], t["idle"]


class Segments(unittest.TestCase):
    def test_steps_checks_and_a_wait_between_steps(self):
        r = run("b-1", 0, 1000, [block("write", 0, 400, 1), block("checks", 400, 700, 2), block("land", 900, 1000, 3)],
                waits=[("land_lock", 700, 200)])
        tl = segments.bead_segments([r], now=T + 2000)
        self.assertEqual([(s["kind"], s["what"], s["secs"]) for s in tl["segments"]],
                         [("work", "write", 400), ("checks", "checks", 300), ("wait", "land_lock", 200), ("work", "land", 100)])
        self.assertEqual(totals(tl), (500, 300, 200, 0))
        self.assertEqual(tl["totals"]["by_what"]["land_lock"], 200)

    def test_a_wait_inside_a_step_is_cut_out_of_it(self):
        r = run("b-1", 0, 600, [block("checks", 0, 600)], waits=[("unity_slot", 100, 200)])
        tl = segments.bead_segments([r], now=T + 700)
        self.assertEqual([(s["kind"], s["secs"]) for s in tl["segments"]], [("checks", 100), ("wait", 200), ("checks", 300)])
        self.assertEqual(sum(totals(tl)), 600)  # nothing is counted twice

    def test_a_wait_longer_than_its_step_is_clipped_to_it(self):
        r = run("b-1", 0, 100, [block("checks", 0, 100)], waits=[("unity_slot", 50, 999)])
        tl = segments.bead_segments([r], now=T + 200)
        self.assertEqual(sum(totals(tl)), 100)

    def test_unexplained_time_inside_a_run_is_idle_only_when_it_is_long(self):
        r = run("b-1", 0, 300, [block("write", 5, 100), block("review", 150, 295)])
        tl = segments.bead_segments([r], now=T + 400)
        self.assertEqual([(s["kind"], s["secs"]) for s in tl["segments"]], [("work", 95), ("idle", 50), ("work", 145)])

    def test_time_between_runs_is_named_by_how_the_first_ended(self):
        a = run("b-1", 0, 100, [block("write", 0, 100)], outcome="asks")
        b = run("b-2", 7300, 7400, [block("write", 7300, 7400)], outcome="paused")
        c = run("b-3", 8000, 8100, [block("write", 8000, 8100)])
        d = run("b-4", 8100, 8200, [block("write", 8100, 8200)])
        tl = segments.bead_segments([a, b, c, d], now=T + 9000)
        gaps = [(s["kind"], s["what"], s["secs"]) for s in tl["segments"] if s["what"] in ("owner_ask", "paused", "between_runs")]
        self.assertEqual(gaps, [("wait", "owner_ask", 7200), ("wait", "paused", 600)])  # 8100 -> 8100 is no gap
        self.assertEqual(tl["totals"]["wait"], 7800)

    def test_nothing_to_show(self):
        self.assertEqual(segments.bead_segments([], now=T)["segments"], [])
        self.assertEqual(segments.bead_segments([{"run": "b-1", "started": None, "blocks": [], "end": {}}], now=T)["t0"], None)


class Review(unittest.TestCase):
    def test_a_live_run_ends_now_so_a_running_bead_reads_to_now(self):
        r = dict(run("b-1", 0, 100, [block("write", 0, 100)]), alive=True)
        tl = segments.bead_segments([r], now=T + 500)
        self.assertEqual(tl["t1"], T + 500)
        self.assertEqual(tl["segments"][-1]["kind"], "idle")

    def test_cuts_never_overlap_or_run_backwards(self):
        r = run("b-1", 0, 100, [block("checks", 0, 100)], waits=[("unity_slot", -1, 0.5), ("unity_slot", 10, 40), ("lane", 30, 40)])
        tl = segments.bead_segments([r], now=T + 200)
        self.assertEqual(sum(totals(tl)), 100)
        self.assertTrue(all(s["t1"] >= s["t0"] for s in tl["segments"]))

    def test_a_wait_before_the_run_does_not_overlap_the_gap_before_it(self):
        a = run("b-1", 0, 100, [block("write", 0, 100)], outcome="asks")
        b = run("b-2", 1000, 1100, [block("write", 1050, 1100)], waits=[("land_lock", 900, 150)])
        tl = segments.bead_segments([a, b], now=T + 2000)
        spans = [(s["t0"], s["t1"]) for s in tl["segments"]]
        self.assertTrue(all(x[1] <= y[0] for x, y in zip(spans, spans[1:])), spans)
        self.assertEqual(sum(totals(tl)), 1100)  # every second of the 1100 is counted once


class FromLogs(unittest.TestCase):
    def write(self, recs):
        return write_log(Path(tempfile.mkdtemp(), "b-1-20261024-010101.jsonl"), recs)

    def test_wait_records_are_read_and_junk_is_skipped(self):
        p = self.write([typed("wait_start", T - 90, id="w1", what="land_lock", holder="o"),
                        typed("wait_end", T, id="w1", secs=90, in_budget=True), {"kind": "wait", "what": "x"}, {"v": 2, "kind": "wait_end"}])
        (w,) = timeline.waits_of(timeline.read(p))
        self.assertEqual((w["what"], w["secs"], w["holder"], w["in_budget"]), ("land_lock", 90, "o", True))

    def test_a_wait_that_is_still_going_is_a_wait_not_idle(self):
        recs = [typed("run_start", T, run="b-1-20261024-010101", bead="b-1", worktree=""),
                typed("step_start", T + 1, id="n1", step="review", text="review"),
                typed("step_end", T + 50, id="n1", step="review", outcome="done", secs=49),
                typed("wait_start", T + 51, id="w1", what="land_lock", holder="o")]
        p = self.write(recs)
        live = timeline.run_timeline(p, alive=True, now=T + 400)
        (w,) = live["waits"]
        self.assertEqual((w["what"], w["secs"], w["open"]), ("land_lock", 349, True))
        tl = segments.bead_segments([live], now=T + 400)
        self.assertEqual([(s["kind"], s["what"]) for s in tl["segments"]], [("work", "review"), ("wait", "land_lock")])
        dead = timeline.run_timeline(p, alive=False, now=T + 400)  # the process died while waiting: it waited until its last record
        self.assertEqual(dead["waits"], [])
        done = self.write(recs + [typed("wait_end", T + 90, id="w1", secs=39, in_budget=True)])
        self.assertEqual([w["secs"] for w in timeline.run_timeline(done)["waits"]], [39])

    def test_a_live_run_ends_now_not_at_its_last_record(self):
        recs = [typed("run_start", T, run="b-1-20261024-010101", bead="b-1", worktree="", started_because="first"),
                typed("step_start", T + 1, id="n1", step="write", text="write"), typed("note", T + 60, text="still writing")]
        p = self.write(recs)
        live = timeline.run_timeline(p, alive=True, now=T + 3600)
        gone = timeline.run_timeline(p, alive=False, now=T + 3600)
        self.assertEqual((live["blocks"][0]["t1"], live["ended"], live["secs"]), (T + 3600, T + 3600, 3600))
        self.assertEqual((gone["blocks"][0]["t1"], gone["ended"]), (T + 60, T + 60))

    def test_a_step_that_has_an_end_record_keeps_it_even_when_alive(self):
        recs = [typed("step_start", T, id="n1", step="write", text="write"),
                typed("step_end", T + 30, id="n1", step="write", outcome="done", secs=30),
                typed("step_start", T + 31, id="n2", step="checks", text="checks")]
        live = timeline.run_timeline(self.write(recs), alive=True, now=T + 500)
        self.assertEqual([(b["kind"], b["t1"]) for b in live["blocks"]], [("write", T + 30), ("checks", T + 500)])


if __name__ == "__main__":
    unittest.main()
