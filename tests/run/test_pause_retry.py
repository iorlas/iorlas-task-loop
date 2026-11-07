"""A durable transient retry keeps the existing checkpoint's plan and starts with write, without another planner call."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te

from taskloop.app.asks import parks
from tlkernel.log import Close
from tlkernel.parks import ParkStore


class Retry(te.EngineTest):
    def test_umbrella_plan_files_followups_and_parks_once_instead_of_finishing(self):
        summary = "Treat this as an umbrella; its children already contain the work"
        plan = dict(te.PLAN, stages=[], summary=summary, leftovers=[{"title": "Follow up", "why": "later"}])
        rc, script = self.run_engine({"plan": [plan]})
        assert rc == 2
        assert script.nodes == ["plan"]
        assert self.eng.result().kind == "noop"
        assert self.eng.result().outcome == "parked"
        assert self.closed == []
        assert self.lands == []
        assert sum(c[:2] == ("create", "Follow up") for c in self.bd_calls) == 1
        paused = ParkStore(self.eng.home).get(self.eng.bead)
        assert paused is not None
        assert (paused.reason, paused.permanence, paused.retry_at) == ("plan_noop", "needs_owner", 0)
        bead = self.store.show(self.eng.bead)
        assert bead is not None
        assert parks.skip_of(self.eng.home, bead, now=paused.t + 1_000_000) is not None
        ask = self.asks().get(self.eng.bead)
        assert ask is not None
        assert ask.detail.text == (f"The plan finds nothing to implement for {self.eng.bead}: {summary}. "
                         "Close it, or give it work.")
        assert len([a for a in self.asks().rows() if a.bead == self.eng.bead and a.event == "raise"]) == 1
        closes = [row.rec for row in self.eng.stores.run_log(self.eng.run_id).read_from(0).items if isinstance(row.rec, Close)]
        assert [row.outcome for row in closes] == ["noop"]
        assert closes[0].why == "noop: the plan found nothing to implement: " + summary

    def test_transient_retry_reuses_the_completed_plan_when_inputs_are_unchanged(self):
        later = te.stop("rate_limited", at=10**12)
        rc, first = self.run_engine({"plan": [te.PLAN], "write": [later]})
        assert rc == 2
        assert first.nodes.count("plan") == 1
        paused = ParkStore(self.eng.home).get(self.eng.bead)
        assert paused is not None
        assert (paused.reason, paused.permanence) == ("rate_limited", "transient")
        assert paused.retry_at > paused.t
        assert self.eng.retry_after == paused.retry_at
        closes = [row.rec for row in self.eng.stores.run_log(self.eng.run_id).read_from(0).items if isinstance(row.rec, Close)]
        assert [row.retry_at for row in closes] == [paused.retry_at]
        with mock.patch.object(parks, "time", mock.Mock(time=lambda: paused.retry_at)):
            rc, second = self.run_engine({"write": [te.WRITE], "review": [te.CLEAN]})
        assert rc == 0
        assert "plan" not in second.nodes
        assert second.nodes[0] == "write"
        assert ParkStore(self.eng.home).get(self.eng.bead) is None

    def test_machine_owner_pause_has_no_ask_and_no_timer(self):
        stopped = te.stop("no_lane")
        stopped["stop"]["reason"] = "engine_only_unenforced"
        rc, _ = self.run_engine({"plan": [te.PLAN], "write": [stopped]})
        assert rc == 2
        rec = ParkStore(self.eng.home).get(self.eng.bead)
        assert rec is not None
        assert (rec.reason, rec.permanence, rec.retry_at) == ("engine_only_unenforced", "needs_owner", 0)
        assert self.ask() is None
        assert not self.eng.asked

    def test_no_lane_and_delegate_crash_need_owner_even_with_a_retry_hint(self):
        for reason in ("no_lane", "crash"):
            with self.subTest(reason=reason):
                rc, _ = self.run_engine({"plan": [te.PLAN], "write": [te.stop(reason, at=10**12)]}, fresh=True)
                assert rc == 2
                rec = ParkStore(self.eng.home).get(self.eng.bead)
                assert rec is not None
                assert (rec.reason, rec.permanence, rec.retry_at) == (reason, "needs_owner", 0)
                assert self.eng.retry_after == 0
                assert self.eng.asked == (reason == "crash")
                assert (self.ask() is not None) == (reason == "crash")

    def test_repeated_transient_pause_parks_and_asks_after_three_retries(self):
        for n in range(4):
            answers = {"write": [te.stop("rate_limited", at=10**12)]}
            if n == 0:
                answers["plan"] = [te.PLAN]
            self.run_engine(answers)
        rec = ParkStore(self.eng.home).get(self.eng.bead)
        assert rec is not None
        assert rec.attempts == {"delegate:rate_limited": 4}
        assert (rec.permanence, rec.retry_at) == ("needs_owner", 0)
        assert self.eng.asked
        assert "rate_limited paused 4 times" in str(self.ask())
