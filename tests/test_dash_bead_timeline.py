"""One bead's whole time (tl-9h2): steps, checks, waits and idle as segments with totals; an open step ends now."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import timeline  # noqa: E402

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
        tl = timeline.bead_segments([r], now=T + 2000)
        self.assertEqual([(s["kind"], s["what"], s["secs"]) for s in tl["segments"]],
                         [("work", "write", 400), ("checks", "checks", 300), ("wait", "land_lock", 200), ("work", "land", 100)])
        self.assertEqual(totals(tl), (500, 300, 200, 0))
        self.assertEqual(tl["totals"]["by_what"]["land_lock"], 200)

    def test_a_wait_inside_a_step_is_cut_out_of_it(self):
        r = run("b-1", 0, 600, [block("checks", 0, 600)], waits=[("unity_slot", 100, 200)])
        tl = timeline.bead_segments([r], now=T + 700)
        self.assertEqual([(s["kind"], s["secs"]) for s in tl["segments"]], [("checks", 100), ("wait", 200), ("checks", 300)])
        self.assertEqual(sum(totals(tl)), 600)  # nothing is counted twice

    def test_a_wait_longer_than_its_step_is_clipped_to_it(self):
        r = run("b-1", 0, 100, [block("checks", 0, 100)], waits=[("unity_slot", 50, 999)])
        tl = timeline.bead_segments([r], now=T + 200)
        self.assertEqual(sum(totals(tl)), 100)

    def test_unexplained_time_inside_a_run_is_idle_only_when_it_is_long(self):
        r = run("b-1", 0, 300, [block("write", 5, 100), block("review", 150, 295)])
        tl = timeline.bead_segments([r], now=T + 400)
        self.assertEqual([(s["kind"], s["secs"]) for s in tl["segments"]], [("work", 95), ("idle", 50), ("work", 145)])

    def test_time_between_runs_is_named_by_how_the_first_ended(self):
        a = run("b-1", 0, 100, [block("write", 0, 100)], outcome="asks")
        b = run("b-2", 7300, 7400, [block("write", 7300, 7400)], outcome="paused")
        c = run("b-3", 8000, 8100, [block("write", 8000, 8100)])
        d = run("b-4", 8100, 8200, [block("write", 8100, 8200)])
        tl = timeline.bead_segments([a, b, c, d], now=T + 9000)
        gaps = [(s["kind"], s["what"], s["secs"]) for s in tl["segments"] if s["what"] in ("owner_ask", "paused", "between_runs")]
        self.assertEqual(gaps, [("wait", "owner_ask", 7200), ("wait", "paused", 600)])  # 8100 -> 8100 is no gap
        self.assertEqual(tl["totals"]["wait"], 7800)

    def test_nothing_to_show(self):
        self.assertEqual(timeline.bead_segments([], now=T)["segments"], [])
        self.assertEqual(timeline.bead_segments([{"run": "b-1", "started": None, "blocks": [], "end": {}}], now=T)["t0"], None)


class FromLogs(unittest.TestCase):
    def write(self, recs):
        d = tempfile.mkdtemp()
        p = Path(d, "b-1-20261024-010101.jsonl")
        p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        return str(p)

    def test_wait_records_are_read_and_junk_is_skipped(self):
        p = self.write([{"kind": "wait", "t": T, "what": "land_lock", "text": "land lock", "t0": T - 90, "secs": 90, "holder": "o", "in_budget": True},
                        {"kind": "wait", "what": "x"}, {"kind": "wait", "t0": "no", "secs": 1}])
        (w,) = timeline.waits_of(timeline.read(p))
        self.assertEqual((w["what"], w["secs"], w["holder"], w["in_budget"]), ("land_lock", 90, "o", True))

    def test_a_live_run_ends_now_not_at_its_last_record(self):
        recs = [{"kind": "run", "t": T, "started_because": "first"}, {"kind": "node", "t": T + 1, "id": 1, "step": "write", "text": "write"},
                {"kind": "note", "t": T + 60, "text": "still writing"}]
        p = self.write(recs)
        live = timeline.run_timeline(p, alive=True, now=T + 3600)
        gone = timeline.run_timeline(p, alive=False, now=T + 3600)
        self.assertEqual((live["blocks"][0]["t1"], live["ended"], live["secs"]), (T + 3600, T + 3600, 3600))
        self.assertEqual((gone["blocks"][0]["t1"], gone["ended"]), (T + 60, T + 60))

    def test_a_step_that_has_an_end_record_keeps_it_even_when_alive(self):
        recs = [{"kind": "node", "t": T, "id": 1, "step": "write", "text": "write"},
                {"kind": "end", "t": T + 30, "id": 1, "step": "write", "outcome": "done", "secs": 30},
                {"kind": "node", "t": T + 31, "id": 2, "step": "checks", "text": "checks"}]
        live = timeline.run_timeline(self.write(recs), alive=True, now=T + 500)
        self.assertEqual([(b["kind"], b["t1"]) for b in live["blocks"]], [("write", T + 30), ("checks", T + 500)])


if __name__ == "__main__":
    unittest.main()
