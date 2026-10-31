"""Backend item 5: the engine's typed facts. Every engine comment is a Said record of its step, an assumption is an Assumed record, a
stuck run is one Stuck record per episode (silent past its step's limit, or the same red checks SAME_RED rounds in a row), and the
run records its branch; the dashboard fills Pass.messages, Cell.last, Resumed.branch, the assumptions count and the stuck marker."""

import json
import types
import unittest

import support.paths  # noqa: F401
from support import engine_case as te
from support.dashlogs import RunScript
from support.engine_case import FALSE, PLAN, WRITE
from support.narrow import must

from taskloop.app.run.stuck import StuckTick
from taskloop.contracts import log as rec
from taskloop.contracts.checks import CheckResult, CheckRun
from taskloop.contracts.dash import Marker
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.ids import CheckId
from taskloop.contracts.runlife import SAME_RED, silent_limit
from taskloop.domain.stuck import StuckWatch
from taskloop.stores.memory import MemLog
from taskloop.stores.runlog import RunLog
from taskloop_dash.views import columns, passes
from taskloop_dash.views.runfacts import run_of

T = 1_800_000_000.0
WRITE_LIMIT = silent_limit("write")


def round_of(n, sig="boom", red=True):
    res = CheckResult(id=CheckId("unit"), cmd="python3 -m unittest", group="tests", exit=1 if red else 0,
                      status="failed" if red else "passed", sig=sig)
    return rec.Checks(t=T + n, node_id=f"n{n}", run=CheckRun(round=n, results=[res]))


def watch(*records):
    w = StuckWatch()
    for r in records:
        w.feed(r)
    return w


class Silent(unittest.TestCase):
    START = rec.StepStart(t=T, id="n1", step="write")

    def test_a_step_silent_to_its_limit_is_stuck_once_not_a_second_before(self):
        w = watch(self.START)
        self.assertEqual(w.tick(T + WRITE_LIMIT - 1), [])
        got = w.tick(T + WRITE_LIMIT)
        self.assertEqual([(s.why, s.step, s.since, s.limit_s) for s in got], [("silent", "write", T, WRITE_LIMIT)])
        self.assertEqual(w.tick(T + 3 * WRITE_LIMIT), [])  # one record per episode
        w.feed(got[0])  # the record it wrote, read back at the next tick, is no activity
        self.assertEqual(w.tick(T + 4 * WRITE_LIMIT), [])

    def test_activity_ends_the_episode_and_a_new_silence_is_a_new_one(self):
        w = watch(self.START)
        self.assertEqual(len(w.tick(T + WRITE_LIMIT)), 1)
        w.feed(rec.Note(t=T + WRITE_LIMIT + 5, text="the worker answered"))
        self.assertEqual(w.tick(T + 2 * WRITE_LIMIT), [])
        self.assertEqual(len(w.tick(T + 2 * WRITE_LIMIT + 5)), 1)

    def test_worker_output_and_beats(self):
        w = watch(self.START, rec.Beat(t=T + WRITE_LIMIT - 10))
        w.saw(T + 100)  # the live file was written: the worker talks
        self.assertEqual(w.tick(T + WRITE_LIMIT + 50), [])  # a Beat is no activity, the worker's output is
        self.assertEqual(len(w.tick(T + WRITE_LIMIT + 100)), 1)

    def test_no_open_step_or_an_open_wait_is_never_silent(self):
        ended = watch(self.START, rec.StepEnd(t=T + 1, id="n1", step="write", outcome="done"))
        self.assertEqual(ended.tick(T + 10 * WRITE_LIMIT), [])
        waiting = watch(self.START, rec.WaitStart(t=T + 1, id="w1", what=WaitWhat.LANE))
        self.assertEqual(waiting.tick(T + 10 * WRITE_LIMIT), [])
        waiting.feed(rec.WaitEnd(t=T + 2, id="w1", wait_seconds=1.0))
        self.assertEqual(len(waiting.tick(T + 10 * WRITE_LIMIT)), 1)

    def test_a_said_episode_carries_over_a_move_to_a_newer_install(self):
        w = watch(self.START, rec.Stuck(t=T + WRITE_LIMIT, why="silent", step="write", since=T, limit_s=WRITE_LIMIT))
        self.assertEqual(w.tick(T + 2 * WRITE_LIMIT), [])


class SameRed(unittest.TestCase):
    def test_three_identical_red_rounds_and_not_two(self):
        w = watch(rec.StepStart(t=T, id="n1", step="checks"), round_of(1), round_of(2))
        self.assertEqual(w.tick(T + 3), [])
        w.feed(round_of(3))
        got = w.tick(T + 4)
        self.assertEqual([(s.why, s.step, s.since) for s in got], [("same_red", "checks", T + 1)])
        self.assertEqual(got[0].sig, round_of(3).run.signature())
        w.feed(round_of(4))
        self.assertEqual(w.tick(T + 5), [])  # the episode goes on: said once

    def test_a_green_or_a_different_red_round_breaks_the_row(self):
        for breaker in (round_of(2, red=False), round_of(2, sig="other")):
            with self.subTest(breaker.run.signature()):
                w = watch(round_of(1), breaker, round_of(3), round_of(4))
                self.assertEqual(w.tick(T + 5), [])
                w.feed(round_of(5))
                self.assertEqual(len(w.tick(T + 6)), SAME_RED - 2)

    def test_a_new_episode_after_the_row_broke(self):
        w = watch(round_of(1), round_of(2), round_of(3))
        self.assertEqual(len(w.tick(T + 4)), 1)
        w.feed(round_of(4, red=False))
        for n in (5, 6, 7):
            w.feed(round_of(n))
        self.assertEqual(len(w.tick(T + 8)), 1)


class Tick(unittest.TestCase):
    def test_the_tick_reads_the_log_from_where_it_ended_and_writes_one_record(self):
        clock = types.SimpleNamespace(t=T)
        log = RunLog(MemLog(rec.decode), clock=lambda: clock.t)
        host = types.SimpleNamespace(log=log, live_now="", now=lambda: clock.t)
        tick = StuckTick(host)
        log.emit(rec.StepStart(id="n1", step="write"))
        tick.tick()
        clock.t = T + WRITE_LIMIT
        log.emit(rec.Beat())
        tick.tick()
        clock.t = T + 2 * WRITE_LIMIT
        tick.tick()
        stuck = [i.rec for i in log.log.read_from().items if isinstance(i.rec, rec.Stuck)]
        self.assertEqual([(s.why, s.since, s.t) for s in stuck], [("silent", T, T + WRITE_LIMIT)])


class EngineFacts(te.EngineTest):
    def records(self):
        return [rec.decode(json.loads(x)) for x in self.eng.log_path.read_text().splitlines()]

    def test_every_engine_comment_is_a_said_record_of_its_step(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review(question="Which colour?")]})
        self.assertEqual(rc, 2)
        posted = [c[3] for c in self.store.said("comments", "add")]
        recs = self.records()
        said = [r for r in recs if isinstance(r, rec.Said)]
        self.assertGreaterEqual(len(posted), 3)  # the plan, the ask, Blocked, Reflect
        self.assertEqual([r.text for r in said], posted)
        self.assertEqual({r.who for r in said}, {"engine"})
        steps = {r.id: r.step for r in recs if isinstance(r, rec.StepStart)}
        self.assertTrue(all(r.step in steps for r in said), [r.step for r in said])
        self.assertEqual(steps[said[0].step], "plan")  # the plan summary is said in the plan step
        self.assertTrue(any(r.text.startswith("Blocked: ") and steps[r.step] == "close" for r in said))

    def test_the_run_records_its_branch(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]})
        self.assertEqual(rc, 0)
        start = next(r for r in self.records() if isinstance(r, rec.RunStart))
        self.assertEqual(start.branch, "task/t-1")

    def test_the_third_same_red_round_is_one_stuck_record_before_the_close(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, _s = self.run_engine({"plan": [plan], "write": [WRITE] * 4}, max_check_tries=1)
        self.assertEqual(rc, 2)
        recs = self.records()
        stuck = [r for r in recs if isinstance(r, rec.Stuck)]
        self.assertEqual([s.why for s in stuck], ["same_red"])
        kinds = [type(r).__name__ for r in recs]
        self.assertLess(kinds.index("Stuck"), kinds.index("Close"))
        dash = run_of(self.eng.log_path.stem, recs, recs[-1].t)
        self.assertIsNotNone(dash.stuck)
        self.assertEqual(passes.passes_of([dash])[-1].end, "stuck")


class DashFacts(unittest.TestCase):
    def test_messages_and_cell_last_come_from_said(self):
        s = RunScript("tl-9").step("plan", 60).add("said", step="n1", who="engine", text="Plan (engine): 2 stages\nmore")
        s.step("write", 60).add("said", step="n2", who="owner", text="use the blue one")
        s.add("said", step="n2", who="engine", text="Lane (engine): fell back")
        p = passes.passes_of([s.run(s.t)])[0]
        got = passes.pass_rec(p)
        self.assertEqual([(m.icon, m.who, m.md) for m in got.messages],
                         [("⚙️", "engine", "Lane (engine): fell back"), ("✉️", "owner", "use the blue one"),
                          ("⚙️", "engine", "Plan (engine): 2 stages\nmore")])
        last = {c.phase.value: c.last for c in got.cells}
        self.assertEqual((last["plan"], last["write"], last["test"]), ("Plan (engine): 2 stages", "Lane (engine): fell back", ""))

    def test_a_live_stuck_run_is_the_stuck_marker_cell_and_end(self):
        s = RunScript("tl-9").step("plan", 60).step("write", 60, end=False)
        s.add("stuck", why="silent", step="write", since=s.t - 60, limit_s=WRITE_LIMIT).beat()
        run = s.run(s.t + 10)
        self.assertIsNotNone(run.stuck)
        p = passes.passes_of([run])[-1]
        self.assertEqual(p.end, "stuck")
        self.assertIn("stuck", [c.state for c in passes.cells_of(p)])
        f = columns.Facts(claimed=True, life=run.life, phase=must(run.current()).phase, stuck=True,
                          stuck_line=passes.stuck_text(must(run.stuck)))
        self.assertEqual(columns.marker(f), Marker.STUCK)
        self.assertEqual(columns.status_line(f), "stuck: silent past 30m in write")
        s.add("note", text="the worker answered")  # new activity: the episode is over
        self.assertIsNone(s.run(s.t + 10).stuck)

    def test_resumed_names_the_branch_the_run_recorded(self):
        a = RunScript("tl-9", stamp="20261015-100000").step("write", 60).close("parked", why_code="lane_out")
        b = RunScript("tl-9", stamp="20261015-110000", slot="b", at=3600, prev_run=a.name)
        b.rows[0]["branch"] = "task/tl-9"
        b.step("write", 60)
        ps = passes.passes_of([a.run(b.t), b.run(b.t)])
        self.assertEqual(must(ps[-1].resumed).branch, "task/tl-9")


if __name__ == "__main__":
    unittest.main()
