"""A fetch pause keeps each loop alive and bypasses all failure accounting."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from slots.test_slot_pool import Rig
from support.fake_loop_env import slot_loop_env

from taskloop.app.asks import parks
from taskloop.app.loop import verdict as vd
from taskloop.app.loop.gate import GateRole
from taskloop.app.loop.net import NetState
from taskloop.app.loop.settle import Counters, Settle
from taskloop.app.loop.take import Taker
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.slots import SlotGitError
from taskloop.domain import outcome, storm

DNS = "fatal: unable to access 'https://github.com/org/repo': Could not resolve host: github.com"


class FetchNetwork(Rig):
    def test_slot_fetch_stops_before_checkout_and_enters_network_wait(self):
        env = slot_loop_env(self.env)
        bid = BeadId("x-1")
        self.bd.beads[bid] = Bead(id=bid, title="work", status="in_progress", assignee=self.env.actor)
        taker = Taker(env, mock.Mock(), LoopConfig, self.out.append, mock.Mock(), {})
        with mock.patch.object(self.git, "fetch", side_effect=SlotGitError(DNS)):
            verdict = taker.prepare("s1", bid)
        assert verdict is not None
        self.assertTrue(verdict.paused_for_network)
        self.assertTrue(verdict.pre_engine)
        self.assertEqual(self.bd.beads[bid].status, "open")
        self.assertEqual(self.bd.beads[bid].labels, [])
        self.assertFalse({"checkout", "checkout_new", "clean"} & {c[0] for c in self.git.calls})

    def test_four_loops_pause_without_runs_failures_cooldowns_or_storm_exit(self):
        for lane in range(4):
            with self.subTest(lane=lane):
                env = slot_loop_env(self.env)
                probe = mock.Mock()
                probe.up.side_effect = [False, True]
                env.probe = mock.Mock(return_value=probe)
                files, left = mock.Mock(), mock.Mock()
                counts, net = Counters(), NetState(60)
                settle = Settle(env, files, LoopConfig, self.out.append, counts,
                                GateRole(lambda: {}, lambda: 0.0), net, left)
                v = vd.Verdict(Result.PAUSED, f"paused: `git fetch -q origin`: {DNS}", kind=vd.NETWORK,
                               pre_engine=bool(lane % 2))
                self.assertIsNone(settle.apply(v, "x-1", "s1", True))
                self.assertTrue(net.down)
                self.assertEqual((counts.ran, counts.fails, counts.pauses, counts.later), (0, [], {}, {}))
                self.assertEqual(counts.net_first, ["x-1"])
                left.assert_not_called()
                files.rest_bead.assert_not_called()
                self.assertFalse(net.poll(probe, self.t[0]))
                self.assertFalse(net.poll(probe, self.t[0] + 59))
                self.assertTrue(net.poll(probe, self.t[0] + 60))
                self.assertFalse(net.down)

    def test_network_fetch_pauses_never_feed_storm_or_escalate(self):
        done = outcome.make(Kind.PAUSE_NETWORK, f"paused: `git fetch -q origin`: {DNS}")
        history = []
        for n in range(20):
            bead = f"x-{n % 4}"
            decision = outcome.apply(done, bead, history, 100 + n)
            self.assertEqual(decision.kind, Kind.PAUSE_NETWORK)
            self.assertFalse(decision.escalated)
            self.assertFalse(decision.ask)
            self.assertIsNone(storm.storm_trip(history, bead, done.kind, done.fingerprint, 100 + n))
            history.append({"bead": bead, "kind": done.kind.value, "fingerprint": done.fingerprint, "t": 100 + n})

    def test_network_history_cannot_contribute_to_a_later_fault_storm(self):
        done = outcome.make(Kind.FAULT_INFRA, DNS)
        history = [{"bead": "x-1", "kind": Kind.PAUSE_NETWORK.value, "fingerprint": done.fingerprint, "t": 100}]
        self.assertIsNone(storm.storm_trip(history, "x-2", done.kind, done.fingerprint, 101))

    def test_pre_engine_network_classification_keeps_other_errors_as_infrastructure(self):
        self.assertTrue(vd.pre_engine(DNS).paused_for_network)
        other = vd.pre_engine("Permission denied (publickey)")
        self.assertEqual(other.kind, "transient_infrastructure")
        self.assertFalse(other.paused_for_network)

    def test_durable_network_pause_does_not_add_a_loop_cooldown(self):
        env = slot_loop_env(self.env)
        env.probe = mock.Mock(return_value=mock.Mock())
        bid = BeadId("x-1")
        bead = Bead(id=bid, title="work", status="open")
        rec = parks.paused(env.cfgdir, bead, Kind.PAUSE_NETWORK, "run-1", env.now())
        assert rec is not None
        self.assertEqual((rec.attempts, rec.runs), ({}, 0))
        files, left = mock.Mock(), mock.Mock()
        counts, net = Counters(), NetState()
        settle = Settle(env, files, LoopConfig, self.out.append, counts, GateRole(lambda: {}, lambda: 0.0), net, left)
        v = vd.Verdict(Result.PAUSED, DNS, kind=vd.NETWORK, run="run-1")
        self.assertIsNone(settle.apply(v, bid, "s1", True))
        self.assertTrue(net.down)
        self.assertEqual((counts.ran, counts.fails, counts.pauses, counts.later), (0, [], {}, {}))
        left.assert_not_called()
        files.rest_bead.assert_not_called()
