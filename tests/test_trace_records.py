"""The engine's machine-readable trace (node, end, transition, checks, run records) and the dashboard timeline built
from it: the contract between engine.py and dash/server.py (docs/design/dashboard.md, Timeline records)."""

import json
import sys
import time
import unittest
from pathlib import Path

import test_engine as te
from test_engine import CLEAN, FALSE, HAS_F, PLAN, PY, WRITE, review, stop

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import server  # noqa: E402

engine, tl = te.engine, te.tl

# red the first time it runs, green after: the fake writer writes d<call number> to f.txt (plan = call 1)
GREEN_ON_2ND_WRITE = PY + ' -c "import sys; sys.exit(0 if open(\'f.txt\').read().strip() == \'d3\' else 1)"'


def records(eng, kind=None):
    out = [json.loads(x) for x in eng.log_path.read_text().splitlines()]
    return [r for r in out if kind is None or r["kind"] == kind]


class TraceRecords(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine = (te.EngineTest.setUp, te.EngineTest.tearDown, te.EngineTest.fake_bd,
                                            te.EngineTest.run_engine)
    commit_base_cfg = te.EngineTest.commit_base_cfg

    def steps(self):
        return [(r["id"], r["step"]) for r in records(self.eng, "node")]

    def transitions(self):
        return [(r["from"], r["to"], r["cause"]) for r in records(self.eng, "transition")]

    def test_every_node_has_an_id_a_step_its_counters_and_an_end(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(self.steps(), [(1, "reset"), (2, "plan"), (3, "write"), (4, "checks"), (5, "review"),
                                        (6, "land"), (7, "close")])
        nodes = {r["id"]: r for r in records(self.eng, "node")}
        self.assertEqual(nodes[3]["text"], "write: stage 1/1 write 1")  # the old text stays: tl.event and the loop read it
        self.assertEqual({k: nodes[3].get(k) for k in ("stage", "stages", "write", "round")},
                         {"stage": 1, "stages": 1, "write": 1, "round": 1})
        self.assertEqual(nodes[6]["try"], 1)
        ends = {r["id"]: r for r in records(self.eng, "end")}
        self.assertEqual(sorted(ends), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(ends[4]["outcome"], "green")
        self.assertEqual(ends[5]["outcome"], "clean")
        self.assertEqual(ends[6]["outcome"], "landed")
        self.assertEqual(ends[7]["outcome"], "landed")
        self.assertEqual(ends[3]["sessions"], ["ref-write"])
        for e in ends.values():
            self.assertGreaterEqual(e["t"], nodes[e["id"]]["t"])
        sess = records(self.eng, "session")
        self.assertEqual([(s["node_id"], s["resume"]) for s in sess], [(2, False), (3, False), (5, False)])
        self.assertEqual([m["node_id"] for m in records(self.eng, "msg")], [2, 3, 5])
        self.assertIn((5, "next", "accepted"), self.transitions())
        self.assertIn((6, "close", "landed"), self.transitions())

    def test_red_checks_go_back_to_the_writer_and_every_check_round_is_kept(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[GREEN_ON_2ND_WRITE])])
        rc, _ = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([s for _, s in self.steps()], ["reset", "plan", "write", "checks", "write", "checks", "review",
                                                        "land", "close"])
        self.assertIn((4, "write", "checks_red"), self.transitions())
        red = next(r for r in records(self.eng, "transition") if r["cause"] == "checks_red")
        self.assertIn("1 failed", red["detail"])
        second = next(r for r in records(self.eng, "node") if r["id"] == 5)
        self.assertEqual((second["write"], second["round"]), (2, 1))
        rounds = records(self.eng, "checks")
        self.assertEqual([(r["node_id"], r["round"]) for r in rounds], [(4, 1), (6, 2)])
        self.assertEqual([i["status"] for i in rounds[0]["items"]], ["failed"])
        self.assertEqual([i["status"] for i in rounds[1]["items"]], ["ran"])
        item = rounds[0]["items"][0]
        for k in ("id", "cmd", "exit", "status", "secs", "tries", "log"):
            self.assertIn(k, item)
        self.assertEqual(item["exit"], 1)
        run = self.eng.run_dir
        self.assertTrue((run / rounds[0]["items"][0]["log"]).exists())
        self.assertTrue((run / rounds[1]["items"][0]["log"]).exists())
        self.assertNotEqual(rounds[0]["items"][0]["log"], rounds[1]["items"][0]["log"])
        self.assertTrue((run / "engine-checks.r1.json").exists())
        self.assertTrue((run / "engine-checks.r2.json").exists())
        self.assertTrue((run / "engine-checks.json").exists())  # the latest round, as before

    def test_a_review_that_sends_the_stage_back_is_a_round_with_its_reason(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["a"], findings=[te.finding("high")]), CLEAN]})
        self.assertEqual(rc, 0)
        t = next(r for r in records(self.eng, "transition") if r["cause"] == "review_sendback")
        self.assertEqual((t["from"], t["to"]), (5, "write"))
        self.assertIn("1 finding", t["detail"])
        self.assertIn("1 unmet", t["detail"])
        ends = {r["id"]: r for r in records(self.eng, "end")}
        self.assertEqual(ends[5]["outcome"], "sent back")
        w2 = next(r for r in records(self.eng, "node") if r["id"] == 6)
        self.assertEqual((w2["write"], w2["round"]), (2, 2))

    def test_a_writer_who_says_the_checks_are_wrong_goes_to_a_replan(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, _ = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertIn((4, "replan", "bad_checks"), self.transitions())
        self.assertEqual(dict(self.steps())[5], "replan")

    def test_a_decision_asks_the_owner(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        self.assertEqual(rc, 2)
        self.assertIn((2, "ask", "decision"), self.transitions())
        ends = {r["id"]: r for r in records(self.eng, "end")}
        self.assertEqual(ends[2]["outcome"], "asks")

    def test_a_resumed_writer_whose_lane_is_out_goes_on_as_a_new_thread(self):
        L = te.DelegateLauncher
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, L.OUT_LONG, L.FRESH],
                                 "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        t = next(r for r in records(self.eng, "transition") if r["cause"] == "lane_out")
        self.assertEqual((t["from"], t["to"]), (6, "write"))
        sess = [s for s in records(self.eng, "session") if s["node_id"] == 6]
        self.assertEqual([(s["status"], s["reason"], s["resume"]) for s in sess], [("stopped", "rate_limited", True), ("done", None, False)])
        self.assertEqual(sess[1]["model"], "sonnet")

    def test_a_long_lane_out_pauses_with_the_time_the_lane_is_back(self):
        due = time.time() + 3 * 3600
        self.run_engine({"plan": [PLAN], "write": [stop("rate_limited", at=due, say="out", lane="OPENAI_SUBSCRIPTION")]})
        t = next(r for r in records(self.eng, "transition") if r["cause"] == "paused")
        self.assertEqual((t["from"], t["to"]), (3, "pause"))
        self.assertAlmostEqual(t["until"], due, delta=1)
        self.assertEqual(t["lane"], "OPENAI_SUBSCRIPTION")
        self.assertEqual({r["id"]: r for r in records(self.eng, "end")}[3]["outcome"], "paused")

    def test_a_red_gate_goes_to_a_fix_round_with_its_counters(self):
        gate = PY + ' -c "import sys; t=open(\'f.txt\').read().strip(); sys.exit(1 if t == \'d2\' else 0)"'
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn((6, "fix", "gate_red"), self.transitions())
        fixw = next(r for r in records(self.eng, "node") if r["step"] == "write" and r.get("fix"))
        self.assertEqual((fixw["fix"], fixw["fixes"], fixw["write"]), (1, 2, 1))
        self.assertEqual(self.steps()[-2:], [(10, "land"), (11, "close")])
        self.assertEqual({r["id"]: r for r in records(self.eng, "end")}[6]["outcome"], "gate red")

    def test_the_trace_says_why_each_run_started_and_which_run_came_before(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        first = self.eng.log_path.stem
        time.sleep(1.05)  # a run's name is its start second
        with self.store.stub(comments=[{"author": "denis", "text": "Old format."}]):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        traces = [json.loads(x) for x in (tl.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual([(t["started_because"], t["prev_run"], t["ask"]) for t in traces],
                         [("first", "", ""), ("answer", first, "t-1-1")])
        run = records(self.eng, "run")[-1]
        self.assertEqual((run["started_because"], run["prev_run"], run["ask"]), ("answer", first, "t-1-1"))
        self.assertEqual(run["run"], self.eng.log_path.stem)

    def test_a_run_after_a_stop_resumes_from_the_checkpoint(self):
        two = te.EngineTest.TWO
        with te.EngineTest.stop_at(self, "reviewer", 2):
            self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN]})
        first = self.eng.log_path.stem
        time.sleep(1.05)
        rc, _ = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        run = records(self.eng, "run")[-1]
        self.assertEqual((run["started_because"], run["prev_run"]), ("resume", first))

    def test_a_rerun_without_a_checkpoint_is_a_retry(self):
        self.run_engine({"plan": [stop("worker_failed", say="boom")] * 2})
        first = self.eng.log_path.stem
        self.assertFalse((tl.config_dir() / "checkpoints" / "t-1.json").exists())
        time.sleep(1.05)
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        run = records(self.eng, "run")[-1]
        self.assertEqual((run["started_because"], run["prev_run"]), ("retry", first))

    def test_check_logs_of_runs_older_than_two_weeks_are_pruned_at_start(self):
        import os
        old = tl.config_dir() / "runs" / "t-0-20261001-000000" / "checks"
        old.mkdir(parents=True)
        for name in ("00-a.r1.log", "00-a.log"):
            (old / name).write_text("x")
            os.utime(str(old / name), (time.time() - 15 * 86400,) * 2)
        new = tl.config_dir() / "runs" / "t-0-20261020-000000" / "checks"
        new.mkdir(parents=True)
        (new / "00-a.r1.log").write_text("x")
        engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)), store=self.store)
        self.assertFalse((old / "00-a.r1.log").exists())
        self.assertTrue((old / "00-a.log").exists())  # an old run's single log is its only one: kept
        self.assertTrue((new / "00-a.r1.log").exists())

    def test_tl_trace_still_reads_the_new_trace(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        out = te.io.StringIO()
        with te.redirect_stdout(out):
            rc = tl.cmd_trace(te.mock.Mock(id="t-1", last=0, json=False))
        self.assertEqual(rc, 0)
        self.assertIn("landed", out.getvalue())

    # ---- the contract: what the engine writes is what the dashboard draws

    def test_the_dashboard_builds_the_runs_blocks_from_the_engines_records(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[GREEN_ON_2ND_WRITE])])
        rc, _ = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        run = server.run_timeline(str(self.eng.log_path))
        self.assertEqual([b["kind"] for b in run["blocks"]], ["plan", "write", "checks", "write", "checks", "review",
                                                              "land"])
        self.assertEqual(run["blocks"][3]["arrow"]["cause"], "checks_red")
        self.assertIn("1 failed", run["blocks"][3]["arrow"]["text"])
        self.assertEqual(run["blocks"][1]["who"]["family"], "openai")
        self.assertEqual(run["blocks"][2]["result"]["status"], "fail")
        self.assertEqual(run["blocks"][4]["result"]["status"], "ok")
        self.assertEqual(run["end"]["outcome"], "landed")
        self.assertEqual(run["started_because"], "first")
        blk = server.block_detail(str(self.eng.log_path), run["blocks"][2]["node"])
        self.assertEqual([c["status"] for c in blk["checks"]], ["failed"])
        self.assertTrue(blk["checks"][0]["log"])


if __name__ == "__main__":
    unittest.main()
