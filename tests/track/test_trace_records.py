"""The engine's machine-readable trace (step, call, transition, checks and run records of the typed EngineLog) and the dashboard
timeline built from it: the contract between the engine and taskloop_dash (taskloop.contracts.log)."""

import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from run import test_engine_units
from support import engine_case as te
from support import homes, procsim
from support.engine_case import CLEAN, FALSE, PLAN, WRITE, review, stop

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support.dashes import make_dash  # noqa: E402
from support.spawn import port_git, real_spawner  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.app.track import verbs  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402
from taskloop.contracts import log as rec  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402
from taskloop.contracts.ids import BeadId  # noqa: E402
from taskloop_dash import jsonl  # noqa: E402

engine = te.engine
DASH = make_dash()

# red the first time it runs, green after: the fake writer writes d<call number> to f.txt (plan = call 1)
GREEN_ON_2ND_WRITE = te.RED_ONCE


def num(ident):
    """The number in a step id ('n4' -> 4)."""
    return int(str(ident).lstrip("n"))


def records(eng, cls=None):
    """The run's typed records, in order; only those of class `cls` when given."""
    return [r for r in jsonl.records(str(eng.log_path)) if cls is None or isinstance(r, cls)]


def calls(eng):
    """[(CallStart, CallEnd)] of the run, one pair per call."""
    starts = {r.id: r for r in records(eng, rec.CallStart)}
    return [(starts[r.id], r) for r in records(eng, rec.CallEnd)]


class TraceRecords(te.EngineTest):

    def steps(self):
        return [(num(r.id), r.step) for r in records(self.eng, rec.StepStart)]

    def transitions(self):
        return [(num(r.from_id), r.to, r.cause) for r in records(self.eng, rec.Transition)]

    def test_every_node_has_an_id_a_step_its_counters_and_an_end(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(self.steps(), [(1, "reset"), (2, "plan"), (3, "write"), (4, "checks"), (5, "review"),
                                        (6, "land"), (7, "close")])
        nodes = {num(r.id): r for r in records(self.eng, rec.StepStart)}
        self.assertEqual(nodes[3].text, "write: stage 1/1 write 1")
        self.assertEqual({k: getattr(nodes[3], k) for k in ("stage", "stages", "write", "round")},
                         {"stage": 1, "stages": 1, "write": 1, "round": 1})
        self.assertIn("(try 1)", nodes[6].text)
        ends = {num(r.id): r for r in records(self.eng, rec.StepEnd)}
        self.assertEqual(sorted(ends), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(ends[4].outcome, "green")
        self.assertEqual(ends[5].outcome, "clean")
        self.assertEqual(ends[6].outcome, "landed")
        self.assertEqual(ends[7].outcome, "landed")
        for e in ends.values():
            self.assertGreaterEqual(e.t, nodes[num(e.id)].t)
        self.assertEqual([(num(s.node), s.resume) for s, _ in calls(self.eng)], [(2, False), (3, False), (5, False)])
        self.assertIn((5, "next", "accepted"), self.transitions())
        self.assertIn((6, "close", "landed"), self.transitions())

    def test_red_checks_go_back_to_the_writer_and_every_check_round_is_kept(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[GREEN_ON_2ND_WRITE])])
        rc, _ = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([s for _, s in self.steps()], ["reset", "plan", "write", "checks", "write", "checks", "review",
                                                        "land", "close"])
        self.assertIn((4, "write", "checks_red"), self.transitions())
        red = next(r for r in records(self.eng, rec.Transition) if r.cause == "checks_red")
        self.assertIn("1 failed", red.detail)
        second = next(r for r in records(self.eng, rec.StepStart) if num(r.id) == 5)
        self.assertEqual((second.write, second.round), (2, 1))
        rounds = records(self.eng, rec.Checks)
        self.assertEqual([(num(r.node_id), r.run.round) for r in rounds], [(4, 1), (6, 2)])
        self.assertEqual([i.status for i in rounds[0].run.results], ["failed"])
        self.assertEqual([i.status for i in rounds[1].run.results], ["passed"])
        item = rounds[0].run.results[0]
        self.assertTrue(item.id and item.cmd and item.log)
        self.assertEqual(item.exit, 1)
        run = self.eng.run_dir
        self.assertTrue((run / rounds[0].run.results[0].log).exists())
        self.assertTrue((run / rounds[1].run.results[0].log).exists())
        self.assertNotEqual(rounds[0].run.results[0].log, rounds[1].run.results[0].log)
        self.assertTrue((run / "engine-checks.r1.json").exists())
        self.assertTrue((run / "engine-checks.r2.json").exists())
        self.assertTrue((run / "engine-checks.json").exists())  # the latest round, as before

    def test_a_review_that_sends_the_stage_back_is_a_round_with_its_reason(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["a"], findings=[te.finding("high")]), CLEAN]})
        self.assertEqual(rc, 0)
        t = next(r for r in records(self.eng, rec.Transition) if r.cause == "review_sendback")
        self.assertEqual((num(t.from_id), t.to), (5, "write"))
        self.assertIn("1 finding", t.detail)
        self.assertIn("1 unmet", t.detail)
        ends = {num(r.id): r for r in records(self.eng, rec.StepEnd)}
        self.assertEqual(ends[5].outcome, "sent back")
        w2 = next(r for r in records(self.eng, rec.StepStart) if num(r.id) == 6)
        self.assertEqual((w2.write, w2.round), (2, 2))

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
        ends = {num(r.id): r for r in records(self.eng, rec.StepEnd)}
        self.assertEqual(ends[2].outcome, "asks")

    def test_a_resumed_writer_whose_lane_is_out_goes_on_as_a_new_thread(self):
        L = test_engine_units.DelegateLauncher
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, L.OUT_LONG, L.FRESH],
                                 "review": [review(unmet=["more"]), CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        t = next(r for r in records(self.eng, rec.Transition) if r.cause == "lane_out")
        self.assertEqual((num(t.from_id), t.to), (6, "write"))
        sess = [(s, e) for s, e in calls(self.eng) if num(s.node) == 6]
        self.assertEqual([(e.status, e.reason, s.resume) for s, e in sess], [("stopped", "rate_limited", True), ("done", None, False)])
        self.assertEqual(sess[1][1].model, "sonnet")

    def test_a_long_lane_out_pauses_with_the_time_the_lane_is_back(self):
        due = time.time() + 3 * 3600
        self.run_engine({"plan": [PLAN], "write": [stop("rate_limited", at=due, say="out", lane="OPENAI_SUBSCRIPTION")]})
        t = next(r for r in records(self.eng, rec.Transition) if r.cause == "paused")
        self.assertEqual((num(t.from_id), t.to), (3, "pause"))
        self.assertEqual({num(r.id): r for r in records(self.eng, rec.StepEnd)}[3].outcome, "paused")

    def test_a_red_gate_goes_to_a_fix_round_with_its_counters(self):
        gate = procsim.fake("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn((6, "fix", "gate_red"), self.transitions())
        fixw = next(r for r in records(self.eng, rec.StepStart) if r.step == "write" and r.fix)
        self.assertEqual((fixw.fix, fixw.write), (1, 1))
        self.assertEqual(self.steps()[-2:], [(10, "land"), (11, "close")])
        self.assertEqual({num(r.id): r for r in records(self.eng, rec.StepEnd)}[6].outcome, "gate red")

    def test_the_trace_says_why_each_run_started_and_which_run_came_before(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        first = self.eng.log_path.stem
        with self.store.stub(comments=[{"author": "denis", "text": "Old format."}]):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        traces = [json.loads(x) for x in (homes.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual([(t["started_because"], t["prev_run"], t["ask"]) for t in traces],
                         [("first", "", ""), ("answer", first, "t-1-1")])
        run = records(self.eng, rec.RunStart)[-1]
        self.assertEqual((run.started_because, run.prev_run, run.ask), ("answer", first, "t-1-1"))
        self.assertEqual(run.run, self.eng.log_path.stem)

    def test_a_run_after_a_stop_resumes_from_the_checkpoint(self):
        two = te.EngineTest.TWO
        with te.EngineTest.stop_at(self, "reviewer", 2):
            self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN]})
        first = self.eng.log_path.stem
        rc, _ = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        run = records(self.eng, rec.RunStart)[-1]
        self.assertEqual((run.started_because, run.prev_run), ("resume", first))

    def test_a_rerun_without_a_checkpoint_is_a_retry(self):
        self.run_engine({"plan": [stop("worker_failed", say="boom")] * 2})
        first = self.eng.log_path.stem
        self.assertFalse((homes.config_dir() / "checkpoints" / "t-1.json").exists())
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        run = records(self.eng, rec.RunStart)[-1]
        self.assertEqual((run.started_because, run.prev_run), ("retry", first))

    def test_check_logs_of_runs_older_than_two_weeks_are_pruned_at_start(self):
        old = homes.config_dir() / "runs" / "t-0-20261001-000000" / "checks"
        old.mkdir(parents=True)
        for name in ("00-a.r1.log", "00-a.log"):
            (old / name).write_text("x")
            os.utime(str(old / name), (time.time() - 15 * 86400,) * 2)
        new = homes.config_dir() / "runs" / "t-0-20261020-000000" / "checks"
        new.mkdir(parents=True)
        (new / "00-a.r1.log").write_text("x")
        engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        self.assertFalse((old / "00-a.r1.log").exists())
        self.assertTrue((old / "00-a.log").exists())  # an old run's single log is its only one: kept
        self.assertTrue((new / "00-a.r1.log").exists())

    def test_tl_trace_still_reads_the_new_trace(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        out = io.StringIO()
        with redirect_stdout(out):
            rc = verbs.trace(BeadId("t-1"), 0, False, snapshot())
        self.assertEqual(rc, 0)
        self.assertIn("landed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
