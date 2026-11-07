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
from taskloop.domain import outcome, storm
from tlkernel.bead import Bead
from tlkernel.config import LoopConfig
from tlkernel.enums import Result
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.slots import SlotGitError

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
        assert verdict.paused_for_network
        assert verdict.pre_engine
        assert self.bd.beads[bid].status == "open"
        assert self.bd.beads[bid].labels == []
        assert not {"checkout", "checkout_new", "clean"} & {c[0] for c in self.git.calls}

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
                assert settle.apply(v, "x-1", "s1", True) is None
                assert net.down
                assert (counts.ran, counts.fails, counts.pauses, counts.later) == (0, [], {}, {})
                assert counts.net_first == ["x-1"]
                left.assert_not_called()
                files.rest_bead.assert_not_called()
                assert not net.poll(probe, self.t[0])
                assert not net.poll(probe, self.t[0] + 59)
                assert net.poll(probe, self.t[0] + 60)
                assert not net.down

    def test_network_fetch_pauses_never_feed_storm_or_escalate(self):
        done = outcome.make(Kind.PAUSE_NETWORK, f"paused: `git fetch -q origin`: {DNS}")
        history = []
        for n in range(20):
            bead = f"x-{n % 4}"
            decision = outcome.apply(done, bead, history, 100 + n)
            assert decision.kind == Kind.PAUSE_NETWORK
            assert not decision.escalated
            assert not decision.ask
            assert storm.storm_trip(history, bead, done.kind, done.fingerprint, 100 + n) is None
            history.append({"bead": bead, "kind": done.kind.value, "fingerprint": done.fingerprint, "t": 100 + n})

    def test_network_history_cannot_contribute_to_a_later_fault_storm(self):
        done = outcome.make(Kind.FAULT_INFRA, DNS)
        history = [{"bead": "x-1", "kind": Kind.PAUSE_NETWORK.value, "fingerprint": done.fingerprint, "t": 100}]
        assert storm.storm_trip(history, "x-2", done.kind, done.fingerprint, 101) is None

    def test_pre_engine_network_classification_keeps_other_errors_as_infrastructure(self):
        assert vd.pre_engine(DNS).paused_for_network
        other = vd.pre_engine("Permission denied (publickey)")
        assert other.kind == "transient_infrastructure"
        assert not other.paused_for_network

    def test_durable_network_pause_does_not_add_a_loop_cooldown(self):
        env = slot_loop_env(self.env)
        env.probe = mock.Mock(return_value=mock.Mock())
        bid = BeadId("x-1")
        bead = Bead(id=bid, title="work", status="open")
        rec = parks.paused(env.cfgdir, bead, Kind.PAUSE_NETWORK, "run-1", env.now())
        assert rec is not None
        assert (rec.attempts, rec.runs) == ({}, 0)
        files, left = mock.Mock(), mock.Mock()
        counts, net = Counters(), NetState()
        settle = Settle(env, files, LoopConfig, self.out.append, counts, GateRole(lambda: {}, lambda: 0.0), net, left)
        v = vd.Verdict(Result.PAUSED, DNS, kind=vd.NETWORK, run="run-1")
        assert settle.apply(v, bid, "s1", True) is None
        assert net.down
        assert (counts.ran, counts.fails, counts.pauses, counts.later) == (0, [], {}, {})
        left.assert_not_called()
        files.rest_bead.assert_not_called()
