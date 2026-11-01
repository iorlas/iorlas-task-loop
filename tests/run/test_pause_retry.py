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
    def test_no_lane_retry_reuses_the_completed_plan_when_inputs_are_unchanged(self):
        rc, first = self.run_engine({"plan": [te.PLAN], "write": [te.stop("no_lane")]}, writer_family=["openai"])
        self.assertEqual(rc, 2)
        self.assertEqual(first.nodes.count("plan"), 1)
        paused = ParkStore(self.eng.home).get(self.eng.bead)
        assert paused is not None
        self.assertEqual((paused.reason, paused.permanence), ("no_lane", "transient"))
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

    def test_owner_pause_keeps_its_old_outcome_no_ask_no_timer_no_park(self):
        stopped = te.stop("no_lane")
        stopped["stop"]["reason"] = "engine_only_unenforced"
        rc, _ = self.run_engine({"plan": [te.PLAN], "write": [stopped]})
        self.assertEqual(rc, 2)
        self.assertIsNone(ParkStore(self.eng.home).get(self.eng.bead))
        self.assertIsNone(self.ask())
