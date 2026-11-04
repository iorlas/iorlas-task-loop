"""tl-7y6.7.3: the loop's pick leaves a parked bead alone while its text is unchanged, with a typed skip reason."""

import sys
import tempfile
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.app.asks import parks
from taskloop.app.loop.loop import Loop
from taskloop.app.loop.queue import QueueRule
from taskloop.app.loop.run import Where
from taskloop.app.loop.take import Taker
from taskloop.app.loop.verdict import Verdict
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.paths import ConfigDir


def bead(desc="do it"):
    return Bead(id=BeadId("t-1"), title="t", status="open", description=desc, acceptance_criteria="- works")


class Pick(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name))

    def rank(self, b):
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _b: "", parked=lambda x: parks.skip_of(self.cfg, x))
        return rule.rank([b], "")

    def test_a_bead_with_no_question_behind_it_is_taken(self):
        q = self.rank(bead())
        assert ([r.bead.id for r in q.ranked], q.skipped) == (["t-1"], [])

    def test_a_run_that_ended_on_a_question_keeps_the_bead_off_the_queue_until_its_text_changes(self):
        parks.ended(self.cfg, bead(), Kind.ASK_STUCK, "run-1", 1.0)
        q = self.rank(bead())
        assert (q.ranked, [(s.bead, s.skip.kind) for s in q.skipped]) == ([], [("t-1", "parked")])
        assert "unchanged" in q.skipped[0].skip.why
        assert [r.bead.id for r in self.rank(bead("do it, and mind the header")).ranked] == ["t-1"]

    def test_two_runs_on_one_text_is_a_hard_skip_and_a_landed_run_clears_it(self):
        parks.ended(self.cfg, bead(), Kind.ASK_STUCK, "run-1", 1.0)
        parks.ended(self.cfg, bead(), Kind.ASK_BUDGET, "run-2", 2.0)
        assert [s.skip.kind for s in self.rank(bead()).skipped] == ["capped"]
        parks.ended(self.cfg, bead(), Kind.LANDED, "run-3", 3.0)
        assert ParkStore(self.cfg).get(BeadId("t-1")) is None

    def test_a_pause_or_a_fault_is_no_question(self):
        for k in (Kind.PAUSE_NETWORK, Kind.FAULT_INFRA, Kind.WAIT_ASK, Kind.OWNER_PARK):
            parks.ended(self.cfg, bead(), k, "run-1", 1.0)
        assert ParkStore(self.cfg).get(BeadId("t-1")) is None

    def test_transient_pause_is_persisted_and_the_queue_wakes_exactly_when_due(self):
        rec = parks.paused(self.cfg, bead(), Kind.PAUSE_LANE, "r1", 100, reason="busy", draw=lambda: 0.5, permanence="transient")
        assert rec is not None
        assert (rec.reason, rec.permanence, rec.retry_at) == ("busy", "transient", 130)
        assert ParkStore(self.cfg).get(bead().id) == rec
        for now, ready in ((129.999, False), (130, True), (131, True)):
            rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "", parked=lambda b, now=now: parks.skip_of(self.cfg, b, now=now))
            q = rule.rank([bead()], "")
            assert bool(q.ranked) == ready
            if not ready:
                assert q.skipped[0].skip.until == 130

    def test_take_path_cannot_claim_early_but_re_takes_a_due_pause_without_owner_action(self):
        parks.paused(self.cfg, bead(), Kind.PAUSE_LANE, "r1", 100, reason="busy", draw=lambda: 0.5, permanence="transient")
        env = mock.Mock(cfgdir=self.cfg, now=mock.Mock(return_value=129), claim=mock.Mock(return_value=(True, "")))
        runner = mock.Mock()
        runner.run.return_value = Verdict(Result.LANDED)
        taker = Taker(env, runner, mock.Mock(), mock.Mock(), mock.Mock(), {})
        at = Where(slot="", wt="/fake", slot_bead=None, started=100)
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "")
        assert taker.attempt_all([bead()], at, False, EngineConfig(), rule, mock.Mock()).verdict is None
        env.claim.assert_not_called()
        env.now.return_value = 130
        got = taker.attempt_all([bead()], at, False, EngineConfig(), rule, mock.Mock())
        assert got.verdict == Verdict(Result.LANDED)
        env.claim.assert_called_once_with(bead().id, "/fake", "")
        runner.run.assert_called_once_with(bead(), at)

    def test_a_queue_of_timed_pauses_waits_instead_of_exiting_drained(self):
        parks.paused(self.cfg, bead(), Kind.PAUSE_LANE, "r1", 100, reason="busy", draw=lambda: 0.5, permanence="transient")
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "", parked=lambda b: parks.skip_of(self.cfg, b, now=100))
        loop = mock.Mock(env=mock.Mock(now=lambda: 100), until=0)
        loop.gate.held = {}  # a timed pause has no role condition; a bare Mock would be truthy
        assert Loop.idle(loop, rule.rank([bead()], "")) is None
        assert (loop.wait.reason, loop.wait.probe_at) == ("no_lane", 130)
        loop.publish.assert_called_once_with()
        loop.nap.assert_called_once_with(30, 0)
        loop.left.assert_not_called()

    def test_a_persisted_deadline_supersedes_a_stale_role_hold_and_cooldown(self):
        parks.paused(self.cfg, bead(), Kind.PAUSE_LANE, "r1", 100, reason="busy", draw=lambda: 0.5, permanence="transient")
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "")
        loop = mock.Mock(env=mock.Mock(cfgdir=self.cfg, now=lambda: 130))
        loop.c.later = {"t-1": 99999}
        loop.c.net_first = []
        loop.files.rests.return_value = {}
        loop.gate.held = {"t-1": ("worker", 100)}
        loop.gate.ready.side_effect = lambda bid: bid not in loop.gate.held
        assert Loop.candidates(loop, rule.rank([bead()], "")) == [bead()]
        assert loop.c.later["t-1"] == 130
