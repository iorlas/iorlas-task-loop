"""tl-ixc: the engine's worker call under the RetryPlan: its six rows, a reviewer's wall-time budget (Overrun), busy answers that cost
at most three sleeps, a write that timed out or ended by SIGTERM (a RetryDecision with the timeout and the exit), and the `exit` in
CallEnd. The policy's own tables are in test_lane_policy; the live file and the stop are in test_write_idle and test_procs."""

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import fake_route
from support.logs import records
from support.spawn import port_git, real_spawner

from taskloop.adapters.delegate import Stopped
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.domain.lanes import retry


def napper(nap):
    """`time` as lane_acts sees it, with a sleep that only counts (the real one is patched nowhere else: threads sleep too)."""
    return SimpleNamespace(sleep=nap, strftime=time.strftime, localtime=time.localtime, time=time.time)


class RetryRows(unittest.TestCase):
    def test_six_kinds_and_every_limit_is_one_row(self):
        got = {r.kind: (r.limit, r.then) for r in retry.ROWS}
        self.assertEqual(
            got,
            {
                "invalid_output": (1, "fault"),
                "denied_read": (1, "fault"),
                "denied_secret": (1, "fault"),
                "lane_poll": (3, "reroute"),
                "crash": (2, "fault"),
                "worker_failed": (1, "ask"),
            },
        )

    def test_left_and_rest_read_the_rows(self):
        self.assertTrue(retry.PLAN.left("lane_poll", 2))
        self.assertFalse(retry.PLAN.left("lane_poll", 3))
        self.assertEqual([retry.PLAN.rest("crash", n) for n in (0, 1, 5)], [30.0, 120.0, 120.0])


class Calls(te.EngineTest):
    def go(self, script):
        c = wslots.load_cfg(str(self.wt))
        nap = mock.Mock()
        with te.delegate_stack(script), mock.patch("taskloop.app.run.lane_acts.time", napper(nap)):
            self.eng = engine.Engine(
                BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git()
            )
            rc = self.eng.run()
        return rc, nap

    def test_a_reviewer_that_never_answers_is_stopped_at_its_budget_and_the_next_rung_reviews(self):
        class Script(fake_route.Script):
            def reply(self, role, *a, **kw):
                if role == "reviewer" and not getattr(self, "hung", False):
                    self.hung = True
                    self.calls.append((role, None, None))
                    self.stop = {"kind": "wall", "why": "wall limit", "alive": []}
                    raise Stopped("wall limit")
                return super().reply(role, *a, **kw)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        rc, _ = self.go(script)
        self.assertEqual(rc, 0)
        over = records(self.eng, "overrun")
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0]["stage"], "review")
        self.assertEqual(over[0]["budget_s"], 600.0)  # the default: review_budget_min 10
        self.assertEqual(script.nodes.count("review"), 1)  # the hung call never answered; the next rung did (the loop went on)

    def test_four_busy_answers_cost_at_most_three_sleeps(self):
        busy = te.stop("busy", "ref-write", say="state lock held")
        script = fake_route.Script(
            {"plan": [te.PLAN], "write": [te.WRITE, busy, busy, busy, busy, te.WRITE], "review": [te.review(unmet=["more"]), te.CLEAN]}
        )
        _rc, nap = self.go(script)
        self.assertLessEqual(nap.call_count, 3)

    def test_a_write_that_timed_out_gets_a_retry_decision_with_the_timeout_and_the_exit(self):
        class Script(fake_route.Script):
            def reply(self, role, *a, **kw):
                if role == "worker" and not getattr(self, "timed", False):
                    self.timed = True
                    self.calls.append((role, None, None))
                    return fake_route.answer(self.c, "worker_failed", "r1", exit_code=-15)
                return super().reply(role, *a, **kw)

        script = Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        self.go(script)
        dec = records(self.eng, "retry_decision")
        self.assertTrue(dec)
        self.assertEqual(dec[0]["plan"], "worker_failed")
        self.assertEqual(dec[0]["exit"], -15)
        self.assertIn(dec[0]["action"], ("reroute", "new_thread", "retry", "ask"))

    def test_call_end_carries_the_exit_of_the_worker(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.full(te.WRITE, "w1", exit_code=0)], "review": [te.CLEAN]})
        self.go(script)
        ends = [r for r in records(self.eng, "call_end") if r.get("exit") is not None]
        self.assertEqual([r["exit"] for r in ends], [0])  # the write's; the planner and the reviewer ran no worker


for _name in dir(te.EngineTest):  # the engine fixture only
    if _name.startswith("test_") and _name not in Calls.__dict__:
        setattr(Calls, _name, None)


if __name__ == "__main__":
    unittest.main()
