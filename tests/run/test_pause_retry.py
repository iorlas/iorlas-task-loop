"""A durable transient retry keeps the existing checkpoint's plan and starts with write, without another planner call."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te

from taskloop.app.asks import parks
from taskloop.contracts.log import Close
from taskloop.contracts.parks import ParkStore


class Retry(te.EngineTest):
    def test_umbrella_plan_files_followups_and_parks_once_instead_of_finishing(self):
        summary = "Treat this as an umbrella; its children already contain the work"
        plan = dict(te.PLAN, stages=[], summary=summary, leftovers=[{"title": "Follow up", "why": "later"}])
        rc, script = self.run_engine({"plan": [plan]})
        self.assertEqual(rc, 2)
        self.assertEqual(script.nodes, ["plan"])
        self.assertEqual(self.eng.result().kind, "noop")
        self.assertEqual(self.eng.result().outcome, "parked")
        self.assertEqual(self.closed, [])
        self.assertEqual(self.lands, [])
        self.assertEqual(sum(c[:2] == ("create", "Follow up") for c in self.bd_calls), 1)
        paused = ParkStore(self.eng.home).get(self.eng.bead)
        assert paused is not None
        self.assertEqual((paused.reason, paused.permanence, paused.retry_at), ("plan_noop", "needs_owner", 0))
        bead = self.store.show(self.eng.bead)
        assert bead is not None
        self.assertIsNotNone(parks.skip_of(self.eng.home, bead, now=paused.t + 1_000_000))
        ask = self.asks().get(self.eng.bead)
        assert ask is not None
        self.assertEqual(ask.detail.text, f"The plan finds nothing to implement for {self.eng.bead}: {summary}. "
                         "Close it, or give it work.")
        self.assertEqual(len([a for a in self.asks().rows() if a.bead == self.eng.bead and a.event == "raise"]), 1)
        closes = [row.rec for row in self.eng.stores.run_log(self.eng.run_id).read_from(0).items if isinstance(row.rec, Close)]
        self.assertEqual([row.outcome for row in closes], ["noop"])
        self.assertEqual(closes[0].why, "noop: the plan found nothing to implement: " + summary)

    def test_transient_retry_reuses_the_completed_plan_when_inputs_are_unchanged(self):
        later = te.stop("rate_limited", at=10**12)
        rc, first = self.run_engine({"plan": [te.PLAN], "write": [later]}, writer_family=["openai"])
        self.assertEqual(rc, 2)
        self.assertEqual(first.nodes.count("plan"), 1)
        paused = ParkStore(self.eng.home).get(self.eng.bead)
        assert paused is not None
        self.assertEqual((paused.reason, paused.permanence), ("rate_limited", "transient"))
        self.assertGreater(paused.retry_at, paused.t)
        self.assertEqual(self.eng.result().retry_after, paused.retry_at)
        closes = [row.rec for row in self.eng.stores.run_log(self.eng.run_id).read_from(0).items if isinstance(row.rec, Close)]
        self.assertEqual([row.retry_at for row in closes], [paused.retry_at])
        with mock.patch.object(parks, "time", mock.Mock(time=lambda: paused.retry_at)):
            rc, second = self.run_engine({"write": [te.WRITE], "review": [te.CLEAN]}, writer_family=["openai"])
        self.assertEqual(rc, 0)
        self.assertNotIn("plan", second.nodes)
        self.assertEqual(second.nodes[0], "write")
        self.assertIsNone(ParkStore(self.eng.home).get(self.eng.bead))

    def test_owner_pause_has_a_durable_owner_wake_without_a_timer_or_ask(self):
        stopped = te.stop("no_lane")
        stopped["stop"]["reason"] = "engine_only_unenforced"
        rc, _ = self.run_engine({"plan": [te.PLAN], "write": [stopped]})
        self.assertEqual(rc, 2)
        rec = ParkStore(self.eng.home).get(self.eng.bead)
        assert rec is not None
        self.assertEqual((rec.reason, rec.permanence, rec.retry_at), ("engine_only_unenforced", "needs_owner", 0))
        self.assertIsNone(self.ask())

    def test_no_lane_and_delegate_crash_need_owner_even_with_a_retry_hint(self):
        for reason in ("no_lane", "crash"):
            with self.subTest(reason=reason):
                rc, _ = self.run_engine({"plan": [te.PLAN], "write": [te.stop(reason, at=10**12)]}, fresh=True)
                self.assertEqual(rc, 2)
                rec = ParkStore(self.eng.home).get(self.eng.bead)
                assert rec is not None
                self.assertEqual((rec.reason, rec.permanence, rec.retry_at), (reason, "needs_owner", 0))
                self.assertEqual(self.eng.result().retry_after, 0)

    def test_repeated_transient_pause_parks_and_asks_after_three_retries(self):
        for n in range(4):
            answers = {"write": [te.stop("rate_limited", at=10**12)]}
            if n == 0:
                answers["plan"] = [te.PLAN]
            self.run_engine(answers)
        rec = ParkStore(self.eng.home).get(self.eng.bead)
        assert rec is not None
        self.assertEqual(rec.attempts, {"delegate:rate_limited": 4})
        self.assertEqual((rec.permanence, rec.retry_at), ("needs_owner", 0))
        self.assertTrue(self.eng.asked)
        self.assertIn("rate_limited paused 4 times", str(self.ask()))
